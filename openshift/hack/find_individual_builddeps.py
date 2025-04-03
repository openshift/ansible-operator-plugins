import subprocess
import sys
import os
import tempfile

def process_requirements_file(requirements_file):
    """
    Processes requirements file, and 
    finds build deps for individual packages using 'pip_find_builddeps.py'
    https://raw.githubusercontent.com/containerbuildsystem/cachito/master/bin/pip_find_builddeps.py
    """
    packages = []
    with open(requirements_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                packages.append(line)

    for package in packages:
        try:
            print(f"Finding build dependencies for {package}...")

            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_req_file:
                temp_req_filename = temp_req_file.name
                temp_req_file.write(f"{package}\n")

            try:
                subprocess.run([sys.executable, "pip_find_builddeps.py", temp_req_filename], check=True)
                os.remove(temp_req_filename)

                print(f"Finished finding build dependencies for {package}.\n")
        
            except FileNotFoundError:
                print("Error: 'pip_find_builddeps.py' not found. Download it with:\n"
                    "curl -LO https://raw.githubusercontent.com/containerbuildsystem/cachito/master/bin/pip_find_builddeps.py\n"
                    "chmod +x pip_find_builddeps.py")
                sys.exit(1)
            except subprocess.CalledProcessError as e:
                print(f"Error finding build dependencies for {package}: {e}")
                sys.exit(1)

        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            sys.exit(1)



if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python find_individual_builddeps.py <requirements_file>")
        sys.exit(1)

    requirements_file = sys.argv[1]
    process_requirements_file(requirements_file)