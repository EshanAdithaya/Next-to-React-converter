import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import os
import sys
import json
import shutil
import subprocess
import threading
import queue
import logging
from datetime import datetime
from pathlib import Path
import re
from typing import Optional, Dict, List, Tuple
import time

class ConversionLogger:
    def __init__(self, log_widget: scrolledtext.ScrolledText):
        self.log_widget = log_widget
        
        # Setup logging configuration
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        
    def log(self, message: str, level: str = "INFO"):
        """Thread-safe logging to both widget and console"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}\n"
        
        # Log to console
        print(formatted_message.strip())
        
        # Update UI in thread-safe way
        if hasattr(self.log_widget, 'after'):
            self.log_widget.after(0, self._append_log, formatted_message)
    
    def _append_log(self, message: str):
        """Append message to log widget"""
        try:
            self.log_widget.configure(state='normal')
            self.log_widget.insert(tk.END, message)
            self.log_widget.see(tk.END)
            self.log_widget.configure(state='disabled')
        except tk.TclError:
            print("Warning: Failed to update log widget")

class DependencyManager:
    """Handles project dependencies and package management"""
    
    REQUIRED_PACKAGES = [
        'react-router-dom',
        'react-helmet',
        '@emotion/styled',
        '@emotion/react'
    ]
    
    def __init__(self, target_dir: Path, logger: ConversionLogger):
        self.target_dir = target_dir
        self.logger = logger
    
    def check_npm_installation(self) -> bool:
        """Check if npm is installed"""
        try:
            subprocess.run(['npm', '--version'], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.log("npm is not installed. Please install Node.js and npm first.", "ERROR")
            return False
    
    def install_dependencies(self) -> bool:
        """Install required dependencies"""
        if not self.check_npm_installation():
            return False
            
        try:
            self.logger.log("Installing required dependencies...")
            
            for package in self.REQUIRED_PACKAGES:
                self.logger.log(f"Installing {package}...")
                result = subprocess.run(
                    ['npm', 'install', '--save', package],
                    cwd=str(self.target_dir),
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    self.logger.log(f"Failed to install {package}: {result.stderr}", "ERROR")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.log(f"Error installing dependencies: {str(e)}", "ERROR")
            return False

class ProjectAnalyzer:
    def __init__(self, source_dir: str, logger: ConversionLogger):
        self.source_dir = Path(source_dir)
        self.logger = logger
    
    def validate_project(self) -> bool:
        """Validate Next.js project structure"""
        required_files = ['package.json', 'next.config.js']
        required_dirs = ['pages', 'public']
        
        for file in required_files:
            if not (self.source_dir / file).exists():
                self.logger.log(f"Missing required file: {file}", "ERROR")
                return False
        
        for directory in required_dirs:
            if not (self.source_dir / directory).is_dir():
                self.logger.log(f"Missing required directory: {directory}", "ERROR")
                return False
        
        return True
    
    def analyze(self) -> Dict:
        """Analyze the Next.js project structure"""
        if not self.validate_project():
            return {}
            
        try:
            stats = {
                'components': [],
                'pages': [],
                'api_routes': [],
                'styles': [],
                'config_files': [],
                'public_assets': [],
                'dependencies': self._get_dependencies()
            }
            
            # Analyze project structure
            for file in self.source_dir.rglob('*'):
                if file.is_file():
                    rel_path = file.relative_to(self.source_dir)
                    
                    if file.suffix in ['.js', '.jsx', '.tsx', '.ts']:
                        if 'pages' in rel_path.parts:
                            if 'api' in rel_path.parts:
                                stats['api_routes'].append(str(rel_path))
                            else:
                                stats['pages'].append(str(rel_path))
                        elif 'components' in rel_path.parts:
                            stats['components'].append(str(rel_path))
                    elif file.suffix in ['.css', '.scss', '.sass']:
                        stats['styles'].append(str(rel_path))
                    elif file.name in ['next.config.js', 'package.json', 'tsconfig.json']:
                        stats['config_files'].append(str(rel_path))
                    elif 'public' in rel_path.parts:
                        stats['public_assets'].append(str(rel_path))
            
            return stats
            
        except Exception as e:
            self.logger.log(f"Error analyzing project: {str(e)}", "ERROR")
            return {}
    
    def _get_dependencies(self) -> Dict:
        """Extract dependencies from package.json"""
        try:
            package_json = self.source_dir / 'package.json'
            if package_json.exists():
                with open(package_json) as f:
                    data = json.load(f)
                return {
                    'dependencies': data.get('dependencies', {}),
                    'devDependencies': data.get('devDependencies', {})
                }
        except Exception as e:
            self.logger.log(f"Error reading dependencies: {str(e)}", "ERROR")
        return {}

class ProjectConverter:
    def __init__(self, source_dir: str, target_dir: str, logger: ConversionLogger):
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        self.logger = logger
        self.dependency_manager = DependencyManager(self.target_dir, logger)
    
    def setup_react_project(self) -> bool:
        """Initialize new React project"""
        try:
            self.logger.log("Creating new React project...")
            
            # Check if target directory exists
            if self.target_dir.exists():
                self.logger.log("Target directory already exists. Please choose a different location.", "ERROR")
                return False
            
            # Create React project using create-react-app
            result = subprocess.run(
                ['npx', '--yes', 'create-react-app', str(self.target_dir)],
                capture_output=True,
                text=True,
                check=True
            )
            
            self.logger.log("React project created successfully")
            
            # Install additional dependencies
            if not self.dependency_manager.install_dependencies():
                return False
            
            return True
            
        except subprocess.CalledProcessError as e:
            self.logger.log(f"Error creating React project: {e.stderr}", "ERROR")
            return False
        except Exception as e:
            self.logger.log(f"Error setting up React project: {str(e)}", "ERROR")
            return False
    
    def convert_file(self, file_path: Path) -> Optional[str]:
        """Convert a Next.js file to React"""
        try:
            with open(file_path) as f:
                content = f.read()
            
            # Convert Next.js specific code
            content = self._convert_imports(content)
            content = self._convert_routing(content)
            content = self._convert_components(content)
            content = self._convert_data_fetching(content)
            
            return content
            
        except Exception as e:
            self.logger.log(f"Error converting {file_path}: {str(e)}", "ERROR")
            return None
    
    def _convert_imports(self, content: str) -> str:
        """Convert Next.js imports to React equivalents"""
        replacements = {
            r'import\s+.*?\s+from\s+[\'"]next/router[\'"]': 'import { useNavigate, useLocation, useParams } from "react-router-dom"',
            r'import\s+.*?\s+from\s+[\'"]next/link[\'"]': 'import { Link } from "react-router-dom"',
            r'import\s+.*?\s+from\s+[\'"]next/image[\'"]': 'import { LazyLoadImage } from "react-lazy-load-image-component"',
            r'import\s+.*?\s+from\s+[\'"]next/head[\'"]': 'import { Helmet } from "react-helmet"'
        }
        
        for pattern, replacement in replacements.items():
            content = re.sub(pattern, replacement, content)
        return content
    
    def _convert_routing(self, content: str) -> str:
        """Convert Next.js routing to React Router"""
        # Convert useRouter hooks
        content = content.replace('useRouter()', 'useNavigate()')
        content = content.replace('router.push(', 'navigate(')
        content = content.replace('router.replace(', 'navigate(')
        
        # Convert query parameters
        content = content.replace('router.query', 'new URLSearchParams(useLocation().search)')
        
        # Convert Link components
        content = re.sub(
            r'<Link\s+href=([\'"].*?[\'"])',
            r'<Link to=\1',
            content
        )
        
        return content
    
    def _convert_components(self, content: str) -> str:
        """Convert Next.js specific components"""
        # Convert Image component
        content = re.sub(
            r'<Image\s+([^>]*?)src=([\'"].*?[\'"])\s*([^>]*?)/?>',
            r'<LazyLoadImage src=\2 \1 \3 />',
            content
        )
        
        # Convert Head component
        content = re.sub(
            r'<Head>(.*?)</Head>',
            r'<Helmet>\1</Helmet>',
            content,
            flags=re.DOTALL
        )
        
        return content
    
    def _convert_data_fetching(self, content: str) -> str:
        """Convert Next.js data fetching methods"""
        # Convert getStaticProps
        content = re.sub(
            r'export\s+async\s+function\s+getStaticProps\s*\([^)]*\)\s*{([^}]*)}',
            lambda m: self._convert_to_use_effect(m.group(1)),
            content
        )
        
        # Convert getServerSideProps
        content = re.sub(
            r'export\s+async\s+function\s+getServerSideProps\s*\([^)]*\)\s*{([^}]*)}',
            lambda m: self._convert_to_use_effect(m.group(1)),
            content
        )
        
        return content
    
    def _convert_to_use_effect(self, fetch_content: str) -> str:
        """Convert Next.js data fetching to useEffect"""
        return f"""
const [data, setData] = useState(null);
const [loading, setLoading] = useState(true);

useEffect(() => {{
    const fetchData = async () => {{
        try {{
            setLoading(true);
            {fetch_content}
            setData(props);
        }} catch (error) {{
            console.error('Error fetching data:', error);
        }} finally {{
            setLoading(false);
        }}
    }};
    
    fetchData();
}}, []);
"""

class ConverterGUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Next.js to React Converter")
        self.window.geometry("800x600")
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the UI components"""
        # Create main container
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Directory selection
        self._setup_directory_selection(main_frame)
        
        # Log area
        self._setup_log_area(main_frame)
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(
            main_frame,
            variable=self.progress_var,
            maximum=100
        )
        self.progress.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # Convert button
        self.convert_btn = ttk.Button(
            main_frame,
            text="Start Conversion",
            command=self.start_conversion
        )
        self.convert_btn.grid(row=5, column=0, columnspan=3, pady=5)
        
        # Cancel button
        self.cancel_btn = ttk.Button(
            main_frame,
            text="Cancel",
            state=tk.DISABLED,
            command=self.cancel_conversion
        )
        self.cancel_btn.grid(row=5, column=2, pady=5)
        
        self.conversion_active = False
    
    def _setup_directory_selection(self, parent):
        """Setup directory selection widgets"""
        # Source directory
        ttk.Label(parent, text="Source Next.js Project:").grid(row=0, column=0, sticky=tk.W)
        self.source_entry = ttk.Entry(parent, width=50)
        self.source_entry.grid(row=0, column=1, sticky=(tk.W, tk.E))
        ttk.Button(
            parent,
            text="Browse",
            command=lambda: self._browse_directory(self.source_entry)
        ).grid(row=0, column=2, padx=5)
        
        # Target directory
        ttk.Label(parent, text="Target Directory:").grid(row=1, column=0, sticky=tk.W)
        self.target_entry = ttk.Entry(parent, width=50)
        self.target_entry.grid(row=1, column=1, sticky=(tk.W, tk.E))
        ttk.Button(
            parent,
            text="Browse",
            command=lambda: self._browse_directory(self.target_entry)
      ).grid(row=1, column=2, padx=5)
    
    def _setup_log_area(self, parent):
        """Setup logging area"""
        log_frame = ttk.LabelFrame(parent, text="Conversion Log", padding="5")
        log_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        
        self.log_widget = scrolledtext.ScrolledText(
            log_frame,
            height=15,
            width=70,
            state='disabled'
        )
        self.log_widget.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.logger = ConversionLogger(self.log_widget)
    
    def _browse_directory(self, entry_widget):
        """Handle directory selection"""
        directory = filedialog.askdirectory()
        if directory:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, directory)
    
    def start_conversion(self):
        """Start the conversion process"""
        source_dir = self.source_entry.get()
        target_dir = self.target_entry.get()
        
        if not source_dir or not target_dir:
            messagebox.showerror("Error", "Please select both source and target directories")
            return
        
        if not os.path.exists(source_dir):
            messagebox.showerror("Error", "Source directory does not exist")
            return
        
        if os.path.exists(target_dir):
            if not messagebox.askyesno("Warning", "Target directory already exists. Do you want to continue?"):
                return
        
        self.convert_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.conversion_active = True
        self.progress_var.set(0)
        
        # Start conversion in separate thread
        self.conversion_thread = threading.Thread(
            target=self._run_conversion,
            args=(source_dir, target_dir)
        )
        self.conversion_thread.start()
        
        # Start progress update
        self.window.after(100, self._check_conversion_status)
    
    def cancel_conversion(self):
        """Cancel the ongoing conversion process"""
        if self.conversion_active:
            if messagebox.askyesno("Confirm", "Are you sure you want to cancel the conversion?"):
                self.conversion_active = False
                self.logger.log("Conversion cancelled by user", "WARNING")
                self._cleanup_incomplete_conversion()
    
    def _cleanup_incomplete_conversion(self):
        """Clean up partially converted project"""
        target_dir = self.target_entry.get()
        if os.path.exists(target_dir):
            try:
                shutil.rmtree(target_dir)
                self.logger.log("Cleaned up incomplete conversion", "INFO")
            except Exception as e:
                self.logger.log(f"Error cleaning up: {str(e)}", "ERROR")
    
    def _check_conversion_status(self):
        """Check conversion thread status"""
        if self.conversion_thread.is_alive():
            self.window.after(100, self._check_conversion_status)
        else:
            self.convert_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)
            self.conversion_active = False
    
    def _run_conversion(self, source_dir: str, target_dir: str):
        """Run the conversion process"""
        try:
            # Analyze project
            self.logger.log("Analyzing project structure...")
            analyzer = ProjectAnalyzer(source_dir, self.logger)
            project_stats = analyzer.analyze()
            
            if not project_stats:
                self.logger.log("Project analysis failed", "ERROR")
                return
            
            self.logger.log("\nProject Analysis:")
            self.logger.log(f"Components: {len(project_stats['components'])}")
            self.logger.log(f"Pages: {len(project_stats['pages'])}")
            self.logger.log(f"API Routes: {len(project_stats['api_routes'])}")
            self.logger.log(f"Style Files: {len(project_stats['styles'])}")
            self.logger.log(f"Public Assets: {len(project_stats['public_assets'])}")
            
            # Initialize converter
            converter = ProjectConverter(source_dir, target_dir, self.logger)
            
            # Setup React project
            self.progress_var.set(10)
            if not converter.setup_react_project():
                self.logger.log("Failed to create React project", "ERROR")
                return
            
            if not self.conversion_active:
                return
            
            # Convert files
            self._convert_files(converter, project_stats)
            
            # Copy public assets
            if self.conversion_active:
                self._copy_public_assets(source_dir, target_dir, project_stats['public_assets'])
            
            if self.conversion_active:
                self.logger.log("Conversion completed successfully!")
                messagebox.showinfo("Success", "Project conversion completed successfully!")
            
        except Exception as e:
            self.logger.log(f"Conversion failed: {str(e)}", "ERROR")
            messagebox.showerror("Error", f"Conversion failed: {str(e)}")
        finally:
            self.convert_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)
            self.conversion_active = False
    
    def _convert_files(self, converter: ProjectConverter, project_stats: Dict):
        """Convert all project files"""
        total_files = sum(len(files) for files in project_stats.values() if isinstance(files, list))
        processed = 0
        
        for file_type, files in project_stats.items():
            if not isinstance(files, list) or file_type == 'public_assets':
                continue
            
            for file_path in files:
                if not self.conversion_active:
                    return
                    
                self.logger.log(f"Converting {file_path}...")
                
                source_file = converter.source_dir / file_path
                target_file = converter.target_dir / 'src' / file_path
                
                if converted_content := converter.convert_file(source_file):
                    os.makedirs(target_file.parent, exist_ok=True)
                    with open(target_file, 'w', encoding='utf-8') as f:
                        f.write(converted_content)
                
                processed += 1
                self.progress_var.set(10 + (processed / total_files * 70))
    
    def _copy_public_assets(self, source_dir: str, target_dir: str, assets: List[str]):
        """Copy public assets to React project"""
        self.logger.log("Copying public assets...")
        try:
            for asset in assets:
                if not self.conversion_active:
                    return
                    
                source = Path(source_dir) / asset
                target = Path(target_dir) / 'public' / asset.replace('public/', '')
                
                os.makedirs(target.parent, exist_ok=True)
                shutil.copy2(source, target)
            
            self.progress_var.set(100)
            
        except Exception as e:
            self.logger.log(f"Error copying assets: {str(e)}", "ERROR")
    
    def run(self):
        """Start the application"""
        self.window.mainloop()

def main():
    """Main entry point"""
    try:
        app = ConverterGUI()
        app.run()
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()