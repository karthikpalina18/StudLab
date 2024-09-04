import subprocess
import tempfile
import os

def run_code(language, code):
    if language == 'python':
        return run_python_code(code)
    elif language == 'java':
        return run_java_code(code)
    else:
        return "Unsupported language"

def run_python_code(code):
    try:
        result = subprocess.run(
            ['python', '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "Python code timed out"
    except Exception as e:
        return str(e)

def run_java_code(code):
    with tempfile.NamedTemporaryFile(suffix='.java', delete=False) as source_file:
        source_file.write(code.encode())
        source_filename = source_file.name
        class_filename = source_filename.replace('.java', '.class')

    try:
        compile_result = subprocess.run(
            ['javac', source_filename],
            capture_output=True,
            text=True,
            timeout=10
        )
        if compile_result.returncode != 0:
            return compile_result.stderr

        exec_result = subprocess.run(
            ['java', '-cp', os.path.dirname(source_filename), os.path.basename(source_filename).replace('.java', '')],
            capture_output=True,
            text=True,
            timeout=10
        )
        return exec_result.stdout + exec_result.stderr
    except subprocess.TimeoutExpired:
        return "Java code timed out"
    except Exception as e:
        return str(e)
    finally:
        os.remove(source_filename)
        if os.path.exists(class_filename):
            os.remove(class_filename)
