#!/usr/bin/env python3
"""
Script to demonstrate auto-generating Alembic migrations from SQLAlchemy models.

This script shows how to:
1. Import all models to ensure they're registered with SQLAlchemy
2. Use Alembic's auto-generation feature
3. Create migrations based on model changes instead of manual CREATE TABLE statements

Usage:
    python scripts/generate_migration_from_models.py "description of changes"
"""

import sys
import os
import subprocess
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def import_all_models():
    """Import all model files to ensure they're registered with SQLAlchemy."""
    models_dir = project_root / "packages" / "zeroque_common" / "zeroque_common" / "models"
    
    # Import all model modules
    for model_file in models_dir.glob("*.py"):
        if model_file.name != "__init__.py":
            module_name = f"zeroque_common.models.{model_file.stem}"
            print(f"Importing {module_name}...")
            try:
                __import__(module_name)
            except ImportError as e:
                print(f"Warning: Could not import {module_name}: {e}")

def generate_migration(description):
    """Generate a new Alembic migration from model changes."""
    print(f"Generating migration: {description}")
    
    # Run alembic revision with auto-generation
    cmd = [
        "alembic", "revision", "--autogenerate", 
        "-m", description
    ]
    
    try:
        result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Migration generated successfully!")
            print(result.stdout)
        else:
            print("❌ Error generating migration:")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"❌ Error running alembic: {e}")
        return False
    
    return True

def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/generate_migration_from_models.py 'description of changes'")
        print("\nExample:")
        print("python scripts/generate_migration_from_models.py 'add timestamp fields to all models'")
        sys.exit(1)
    
    description = sys.argv[1]
    
    print("🔧 Auto-generating Alembic migration from SQLAlchemy models...")
    print(f"Description: {description}")
    print()
    
    # Step 1: Import all models
    print("Step 1: Importing all models...")
    import_all_models()
    print()
    
    # Step 2: Generate migration
    print("Step 2: Generating migration...")
    success = generate_migration(description)
    
    if success:
        print("\n🎉 Migration generated successfully!")
        print("\nNext steps:")
        print("1. Review the generated migration file")
        print("2. Test the migration: alembic upgrade head")
        print("3. Commit the migration: git add alembic/versions/ && git commit -m 'Auto-generated migration'")
    else:
        print("\n❌ Failed to generate migration")
        sys.exit(1)

if __name__ == "__main__":
    main()

