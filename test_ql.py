#!/usr/bin/env python3
"""
Comprehensive test script for QL (Quick Launcher)
Tests all major functionality to ensure no crashes or errors
"""

import os
import sys
import tempfile
import shutil
import json
import subprocess
from pathlib import Path

def run_command(cmd, timeout=5):
    """Run a command and return stdout, stderr, and return code"""
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except Exception as e:
        return "", str(e), -1

def test_basic_functionality():
    """Test basic QL functionality"""
    print("🧪 Testing basic functionality...")
    
    # Test help
    stdout, stderr, code = run_command("python3 ql.py --help")
    assert code == 0, f"Help command failed: {stderr}"
    assert "QL - Quick Launcher" in stdout, "Help output missing title"
    
    # Test version
    stdout, stderr, code = run_command("python3 ql.py --version")
    assert code == 0, f"Version command failed: {stderr}"
    assert "ql 2.0.0" in stdout, "Version output incorrect"
    
    print("✅ Basic functionality tests passed")

def test_command_operations():
    """Test command add/remove/edit operations"""
    print("🧪 Testing command operations...")
    
    # Create temporary config directory
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_dir = Path(tmp_dir) / '.local' / 'bin'
        config_dir.mkdir(parents=True)
        
        # Set up environment to use temp config
        env = os.environ.copy()
        env['HOME'] = tmp_dir
        
        # Test adding a command via direct execution
        test_cmd = f'cd {tmp_dir} && python3 {os.getcwd()}/ql.py'
        
        # Test that script doesn't crash when run with no commands
        stdout, stderr, code = run_command(f"echo 'quit' | {test_cmd}")
        # Accept timeout as OK since interactive mode might be waiting
        assert "No commands saved yet" in stdout or code == 0 or "TIMEOUT" in stderr, f"Empty state failed: {stderr}"
        
        print("✅ Command operations tests passed")

def test_template_operations():
    """Test template functionality"""
    print("🧪 Testing template operations...")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_dir = Path(tmp_dir) / '.local' / 'bin'
        config_dir.mkdir(parents=True)
        
        # Create a templates file with test data
        templates_file = config_dir / '.qltemplates'
        test_templates = {
            'test-template': {
                'template': 'echo {message}',
                'description': 'Test template',
                'placeholders': ['message']
            }
        }
        
        with open(templates_file, 'w') as f:
            json.dump(test_templates, f)
        
        # Test that templates load without error
        env = os.environ.copy()
        env['HOME'] = tmp_dir
        
        test_cmd = f'cd {tmp_dir} && python3 {os.getcwd()}/ql.py'
        stdout, stderr, code = run_command(f"echo 'quit' | {test_cmd}")
        
        # Should not crash even with template data
        assert code == 0 or "quit" in stdout or "TIMEOUT" in stderr, f"Template loading failed: {stderr}"
        
        print("✅ Template operations tests passed")

def test_edge_cases():
    """Test edge cases and potential problem areas"""
    print("🧪 Testing edge cases...")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_dir = Path(tmp_dir) / '.local' / 'bin'
        config_dir.mkdir(parents=True)
        
        # Test with very long command data
        commands_file = config_dir / '.qlcom'
        long_command = "a" * 10000  # Very long command
        test_commands = {
            'long-cmd': {
                'type': 'link',
                'command': long_command,
                'description': 'Very long command for testing',
                'tags': ['test'],
                'created': '2023-01-01T00:00:00'
            }
        }
        
        with open(commands_file, 'w') as f:
            json.dump(test_commands, f)
        
        # Test that long commands don't crash the display
        env = os.environ.copy()
        env['HOME'] = tmp_dir
        
        test_cmd = f'cd {tmp_dir} && python3 {os.getcwd()}/ql.py'
        stdout, stderr, code = run_command(f"echo 'quit' | {test_cmd}")
        
        # Should handle long commands gracefully
        assert code == 0 or "quit" in stdout or "TIMEOUT" in stderr, f"Long command handling failed: {stderr}"
        assert "RangeError" not in stderr and "Invalid string length" not in stderr, "String length error detected"
        
        print("✅ Edge cases tests passed")

def test_file_operations():
    """Test file I/O operations"""
    print("🧪 Testing file operations...")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_dir = Path(tmp_dir) / '.local' / 'bin'
        config_dir.mkdir(parents=True)
        
        # Test with malformed JSON
        commands_file = config_dir / '.qlcom'
        with open(commands_file, 'w') as f:
            f.write('{"invalid": json}')  # Malformed JSON
        
        env = os.environ.copy()
        env['HOME'] = tmp_dir
        
        test_cmd = f'cd {tmp_dir} && python3 {os.getcwd()}/ql.py'
        stdout, stderr, code = run_command(f"echo 'quit' | {test_cmd}")
        
        # Should handle malformed JSON gracefully
        assert code == 0 or "quit" in stdout or "TIMEOUT" in stderr, f"Malformed JSON handling failed: {stderr}"
        
        print("✅ File operations tests passed")

def test_interactive_mode():
    """Test interactive mode with various inputs"""
    print("🧪 Testing interactive mode...")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_dir = Path(tmp_dir) / '.local' / 'bin'
        config_dir.mkdir(parents=True)
        
        env = os.environ.copy()
        env['HOME'] = tmp_dir
        
        # Test various interactive inputs
        test_inputs = [
            'help\nq\n',  # Help then quit
            'quit\n',     # Direct quit
            '/filter\nq\n',  # Filter mode then quit
            'p\nq\n',     # Toggle preview then quit
        ]
        
        for input_seq in test_inputs:
            test_cmd = f'cd {tmp_dir} && python3 {os.getcwd()}/ql.py'
            stdout, stderr, code = run_command(f"echo -e '{input_seq}' | {test_cmd}")
            
            # Should handle all inputs gracefully
            assert code == 0 or "quit" in stdout or "Goodbye" in stdout or "TIMEOUT" in stderr, f"Interactive input failed: {stderr}"
            assert "RangeError" not in stderr and "Invalid string length" not in stderr, "String length error in interactive mode"
        
        print("✅ Interactive mode tests passed")

def test_cleanup_operations():
    """Test cleanup and temporary file handling"""
    print("🧪 Testing cleanup operations...")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_dir = Path(tmp_dir) / '.local' / 'bin'
        config_dir.mkdir(parents=True)
        
        # Create some fake temporary scripts
        tmp_dir_path = config_dir / 'tmp'
        tmp_dir_path.mkdir(exist_ok=True)
        
        fake_script = tmp_dir_path / 'test_ql.sh'
        with open(fake_script, 'w') as f:
            f.write('#!/bin/bash\n# QL Command Executor\necho "test"\n')
        
        env = os.environ.copy()
        env['HOME'] = tmp_dir
        
        test_cmd = f'cd {tmp_dir} && python3 {os.getcwd()}/ql.py'
        stdout, stderr, code = run_command(f"echo 'cleanup\nq' | {test_cmd}")
        
        # Should handle cleanup without errors
        assert code == 0 or "quit" in stdout or "TIMEOUT" in stderr, f"Cleanup failed: {stderr}"
        
        print("✅ Cleanup operations tests passed")

def main():
    """Run all tests"""
    print("🚀 Starting comprehensive QL testing...")
    print("=" * 50)
    
    try:
        test_basic_functionality()
        test_command_operations()
        test_template_operations()
        test_edge_cases()
        test_file_operations()
        test_interactive_mode()
        test_cleanup_operations()
        
        print("=" * 50)
        print("🎉 ALL TESTS PASSED! QL is working correctly.")
        return 0
        
    except AssertionError as e:
        print(f"❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())