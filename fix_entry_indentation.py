#!/usr/bin/env python3
"""
Script to fix indentation issues in Entry service
"""

import re

def fix_indentation():
    """Fix indentation issues in Entry service"""
    file_path = "services/entry/main.py"
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Fix specific indentation patterns
    patterns = [
        # Fix lines with extra spaces before return
        (r'        (\s+)return \{', r'        return {'),
        # Fix lines with wrong indentation in function bodies
        (r'    (\w+.*=.*)', r'        \1'),
        # Fix orphaned except blocks
        (r'        except Exception:', r'            except Exception:'),
        # Fix return statements outside functions
        (r'^    return \{', r'        return {'),
    ]
    
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    # Write back the fixed content
    with open(file_path, 'w') as f:
        f.write(content)
    
    print("Fixed indentation issues in Entry service")

if __name__ == "__main__":
    fix_indentation()
