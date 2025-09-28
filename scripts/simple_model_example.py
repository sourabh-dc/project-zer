#!/usr/bin/env python3
"""
Simple example showing how to use SQLAlchemy models for auto-generating migrations.

This demonstrates the concept without the complexity of importing all existing models.
"""

import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def create_example_model():
    """Create a simple example model to demonstrate auto-generation."""
    
    from sqlalchemy import String, Integer, DateTime, Boolean
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.sql import func
    from zeroque_common.db.session import Base
    
    class ExampleModel(Base):
        """Example model for demonstrating auto-generation."""
        __tablename__ = "example_models"
        
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        name: Mapped[str] = mapped_column(String(100), nullable=False)
        description: Mapped[str | None] = mapped_column(String(255), nullable=True)
        active: Mapped[bool] = mapped_column(Boolean, default=True)
        created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
        updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    print("✅ Example model created successfully!")
    print("Model: ExampleModel")
    print("Table: example_models")
    print("Fields: id, name, description, active, created_at, updated_at")
    
    return ExampleModel

def demonstrate_auto_generation():
    """Demonstrate how to use Alembic auto-generation."""
    
    print("\n🔧 How to use Alembic auto-generation:")
    print("1. Create or modify SQLAlchemy models")
    print("2. Run: alembic revision --autogenerate -m 'description'")
    print("3. Review the generated migration file")
    print("4. Apply: alembic upgrade head")
    
    print("\n📋 Example workflow:")
    print("# Step 1: Create model (done above)")
    print("# Step 2: Generate migration")
    print("alembic revision --autogenerate -m 'add example_models table'")
    print("# Step 3: Review generated file")
    print("cat alembic/versions/[revision]_add_example_models_table.py")
    print("# Step 4: Apply migration")
    print("alembic upgrade head")

def show_model_benefits():
    """Show the benefits of using models vs manual CREATE TABLE."""
    
    print("\n🎯 Benefits of Model-Based Migrations:")
    print("✅ Single source of truth (models define schema)")
    print("✅ Type safety with SQLAlchemy type hints")
    print("✅ Automatic migration generation")
    print("✅ IDE support with autocomplete")
    print("✅ Consistent across environments")
    print("✅ No manual CREATE TABLE statements")
    
    print("\n📊 Comparison:")
    print("Manual CREATE TABLE:")
    print("  - Write SQL manually")
    print("  - No type checking")
    print("  - Error-prone")
    print("  - Hard to maintain")
    
    print("\nModel-Based:")
    print("  - Define in Python")
    print("  - Type-safe")
    print("  - Auto-generated migrations")
    print("  - Easy to maintain")

def main():
    print("🚀 SQLAlchemy Model-Based Migration Example")
    print("=" * 50)
    
    # Create example model
    create_example_model()
    
    # Show benefits
    show_model_benefits()
    
    # Demonstrate workflow
    demonstrate_auto_generation()
    
    print("\n🎉 Summary:")
    print("Models provide a clean, type-safe way to define database schema.")
    print("Alembic can auto-generate migrations from model changes.")
    print("This eliminates the need for manual CREATE TABLE statements.")

if __name__ == "__main__":
    main()
