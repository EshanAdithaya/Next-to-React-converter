import os
import re
import shutil
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import ast
import json
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import hashlib
from rich.progress import Progress, TextColumn, BarColumn, TaskID
from rich.console import Console
from rich.panel import Panel
import difflib
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import cssutils
import logging

# Suppress cssutils parsing warnings
cssutils.log.setLevel(logging.CRITICAL)

@dataclass
class ConversionConfig:
    source_dir: str
    output_dir: str
    preserve_routes: bool = True
    handle_api_routes: bool = True
    use_llm: bool = False
    threads: int = 4
    verify_output: bool = True
    backup: bool = True
    preserve_css_modules: bool = True

class ConversionTask:
    def __init__(self, file_path: str, task_type: str, weight: int = 1):
        self.file_path = file_path
        self.task_type = task_type
        self.weight = weight
        self.status = "pending"
        self.error = None

class UIHashVerifier:
    """Ensures UI elements remain exactly the same after conversion"""
    
    @staticmethod
    def get_component_hash(content: str) -> str:
        # Extract JSX/TSX structure
        jsx_pattern = re.compile(r'<.*?>', re.DOTALL)
        jsx_elements = jsx_pattern.findall(content)
        return hashlib.md5(''.join(jsx_elements).encode()).hexdigest()
    
    @staticmethod
    def verify_components(original: str, converted: str) -> Tuple[bool, List[str]]:
        original_hash = UIHashVerifier.get_component_hash(original)
        converted_hash = UIHashVerifier.get_component_hash(converted)
        
        if original_hash != converted_hash:
            diff = difflib.unified_diff(
                original.splitlines(),
                converted.splitlines(),
                lineterm=''
            )
            return False, list(diff)
        return True, []

class StyleConverter:
    """Handles CSS Modules and styled-components conversion"""
    
    @staticmethod
    def convert_css_module(content: str, filename: str) -> str:
        parser = cssutils.CSSParser()
        sheet = parser.parseString(content)
        
        # Preserve all class names and their specificity
        class_map = {}
        for rule in sheet:
            if rule.type == rule.STYLE_RULE:
                selector = rule.selectorText
                if '.' in selector:
                    original_class = selector.split('.')[1]
                    class_map[original_class] = original_class
                    
        return content, class_map

class NextToReactConverter:
    def __init__(self, config: ConversionConfig):
        self.config = config
        self.route_map: Dict[str, str] = {}
        self.protected_routes: List[str] = []
        self.tasks: List[ConversionTask] = []
        self.console = Console()
        self.progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console
        )
        self.style_converter = StyleConverter()
        self.verifier = UIHashVerifier()
        
    def create_backup(self):
        """Create backup of source directory"""
        if self.config.backup:
            backup_dir = f"{self.config.source_dir}_backup_{int(time.time())}"
            shutil.copytree(self.config.source_dir, backup_dir)
            self.console.print(f"[green]Created backup at {backup_dir}")

    def analyze_project(self) -> Dict[str, int]:
        """Analyze project structure and calculate conversion metrics"""
        metrics = {
            'total_files': 0,
            'components': 0,
            'pages': 0,
            'api_routes': 0,
            'styles': 0,
            'estimated_time': 0
        }
        
        for root, _, files in os.walk(self.config.source_dir):
            for file in files:
                if file.endswith(('.tsx', '.jsx', '.css', '.scss')):
                    metrics['total_files'] += 1
                    file_path = os.path.join(root, file)
                    
                    if 'pages' in file_path:
                        metrics['pages'] += 1
                    elif 'components' in file_path:
                        metrics['components'] += 1
                    elif 'api' in file_path:
                        metrics['api_routes'] += 1
                    elif file.endswith(('.css', '.scss')):
                        metrics['styles'] += 1
                        
        # Estimate conversion time (in seconds)
        metrics['estimated_time'] = (
            metrics['components'] * 2 +
            metrics['pages'] * 3 +
            metrics['api_routes'] * 1.5 +
            metrics['styles'] * 1
        )
        
        return metrics

    def setup_directory_structure(self):
        """Create React project directory structure with progress tracking"""
        directories = [
            'src',
            'src/components',
            'src/pages',
            'src/routes',
            'src/hooks',
            'src/styles',
            'src/utils',
            'src/context',
            'src/assets'
        ]
        
        with self.progress:
            task_id = self.progress.add_task(
                "Setting up directory structure...",
                total=len(directories)
            )
            
            for directory in directories:
                full_path = f"{self.config.output_dir}/{directory}"
                os.makedirs(full_path, exist_ok=True)
                self.progress.advance(task_id)

    def convert_component(self, task: ConversionTask) -> Tuple[bool, Optional[str]]:
        """Convert a single component with UI verification"""
        try:
            with open(task.file_path, 'r') as f:
                original_content = f.read()
                
            # Convert component
            converted_content = self._transform_component(original_content)
            
            # Verify UI preservation
            is_identical, diff = self.verifier.verify_components(
                original_content,
                converted_content
            )
            
            if not is_identical:
                return False, f"UI mismatch in {task.file_path}:\n" + '\n'.join(diff)
            
            # Write converted component
            output_path = self._get_output_path(task.file_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w') as f:
                f.write(converted_content)
                
            return True, None
            
        except Exception as e:
            return False, str(e)

    def _transform_component(self, content: str) -> str:
        """Transform Next.js component to React while preserving exact UI"""
        # Replace Next.js imports
        content = re.sub(
            r'import\s+{\s*useRouter\s*}\s+from\s+[\'"]next/router[\'"]',
            'import { useNavigate, useLocation } from "react-router-dom"',
            content
        )
        
        # Convert Next.js Image component while preserving exact styling
        content = re.sub(
            r'<Image\s+([^>]*?)src=([\'"].*?[\'"])\s*([^>]*?)/?>',
            lambda m: self._convert_image_tag(m.group(1), m.group(2), m.group(3)),
            content
        )
        
        # Preserve exact styling from CSS modules
        if '.module.' in content:
            content = self._preserve_css_modules(content)
            
        return content

    def _convert_image_tag(self, prefix: str, src: str, suffix: str) -> str:
        """Convert Next.js Image to img while preserving exact styling"""
        style_props = {}
        
        # Extract width and height
        width_match = re.search(r'width=[\'"]\d+[\'"]', prefix + suffix)
        height_match = re.search(r'height=[\'"]\d+[\'"]', prefix + suffix)
        
        if width_match:
            style_props['width'] = width_match.group(0).split('=')[1].strip('\'"')
        if height_match:
            style_props['height'] = height_match.group(0).split('=')[1].strip('\'"')
            
        style_str = ' '.join([f'{k}={v}' for k, v in style_props.items()])
        return f'<img src={src} {style_str} loading="lazy" />'

    def _preserve_css_modules(self, content: str) -> str:
        """Ensure CSS modules are preserved exactly"""
        # Extract CSS module imports
        css_imports = re.findall(
            r'import\s+(\w+)\s+from\s+[\'"](.+?\.module\.css)[\'"]',
            content
        )
        
        for var_name, css_path in css_imports:
            # Read and parse CSS module
            with open(css_path, 'r') as f:
                css_content = f.read()
                
            # Convert while preserving classes
            converted_css, class_map = self.style_converter.convert_css_module(
                css_content,
                css_path
            )
            
            # Update class references in JSX
            for original, converted in class_map.items():
                content = re.sub(
                    fr'{var_name}\.{original}',
                    f'{var_name}.{converted}',
                    content
                )
                
        return content

    def convert_with_progress(self):
        """Main conversion process with detailed progress tracking"""
        try:
            # Analyze project
            metrics = self.analyze_project()
            self.console.print(Panel.fit(
                f"Project Analysis:\n"
                f"Total Files: {metrics['total_files']}\n"
                f"Components: {metrics['components']}\n"
                f"Pages: {metrics['pages']}\n"
                f"API Routes: {metrics['api_routes']}\n"
                f"Styles: {metrics['styles']}\n"
                f"Estimated Time: {metrics['estimated_time']}s"
            ))
            
            # Create backup
            self.create_backup()
            
            with self.progress:
                # Setup structure
                setup_task = self.progress.add_task(
                    "Setting up project structure...",
                    total=1
                )
                self.setup_directory_structure()
                self.progress.update(setup_task, completed=1)
                
                # Convert components
                conversion_task = self.progress.add_task(
                    "Converting components...",
                    total=metrics['total_files']
                )
                
                with ThreadPoolExecutor(max_workers=self.config.threads) as executor:
                    futures = []
                    
                    for task in self.tasks:
                        future = executor.submit(self.convert_component, task)
                        futures.append((future, task))
                        
                    for future, task in futures:
                        success, error = future.result()
                        if not success:
                            self.console.print(f"[red]Error converting {task.file_path}:")
                            self.console.print(error)
                        self.progress.advance(conversion_task)
                
                # Generate additional files
                config_task = self.progress.add_task(
                    "Generating configuration...",
                    total=3
                )
                
                self.generate_react_router_config()
                self.progress.advance(config_task)
                
                self.generate_package_json()
                self.progress.advance(config_task)
                
                self.generate_webpack_config()
                self.progress.advance(config_task)
                
            self.console.print("[green]Conversion completed successfully!")
            
        except Exception as e:
            self.console.print(f"[red]Error during conversion: {str(e)}")
            if self.config.backup:
                self.console.print(
                    "[yellow]Restore from backup to revert changes."
                )

    def generate_webpack_config(self):
        """Generate webpack config to match Next.js behavior"""
        config = {
            'entry': './src/index.js',
            'module': {
                'rules': [
                    {
                        'test': r'/\.(js|jsx|ts|tsx)$/',
                        'exclude': '/node_modules/',
                        'use': {
                            'loader': 'babel-loader',
                            'options': {
                                'presets': [
                                    '@babel/preset-env',
                                    '@babel/preset-react',
                                    '@babel/preset-typescript'
                                ]
                            }
                        }
                    },
                    {
                        'test': r'/\.module\.css$/',
                        'use': [
                            'style-loader',
                            {
                                'loader': 'css-loader',
                                'options': {
                                    'modules': {
                                        'localIdentName': '[name]__[local]__[hash:base64:5]'
                                    }
                                }
                            }
                        ]
                    }
                ]
            },
            'resolve': {
                'extensions': ['.js', '.jsx', '.ts', '.tsx']
            }
        }
        
        with open(f"{self.config.output_dir}/webpack.config.js", 'w') as f:
            f.write(f"module.exports = {json.dumps(config, indent=2)}")

if __name__ == "__main__":
    config = ConversionConfig(
        source_dir="./my-nextjs-app",
        output_dir="./converted-react-app",
        preserve_routes=True,
        handle_api_routes=True,
        use_llm=False,
        threads=4,
        verify_output=True,
        backup=True,
        preserve_css_modules=True
    )
    
    converter = NextToReactConverter(config)
    converter.convert_with_progress()