#!/usr/bin/env python3
"""
Set up default categories for the booking system.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Category, Service

# Default categories in display order
DEFAULT_CATEGORIES = [
    'Ears',
    'Nose',
    'Lips',
    'Face',
    'Body',
    'Under 16s',
    'Consultation',
    'Service',
    'Other'
]

# Mapping of service name patterns to categories
CATEGORY_MAPPINGS = {
    'Ears': ['Ear', 'Helix', 'Conch', 'Flat', 'Daith', 'Tragus', 'Rook', 'Industrial', 'Lobe'],
    'Nose': ['Nostril', 'Septum', 'Nose'],
    'Lips': ['Labret', 'Philtrum', 'Medusa', 'Lip'],
    'Face': ['Bridge', 'Eyebrow'],
    'Body': ['Nipple', 'Navel', 'Both Nipples'],
    'Under 16s': ['Teen', 'Children'],
    'Consultation': ['Consultation', 'Anatomy', 'Mapping', 'Ear consultation'],
    'Service': ['Downsize', 'Health Check', 'Swell', 'MRI', 'Medical', 'Jewellery change', 'Jewellery Change'],
    'Other': ['Chain Fitting']
}


def setup_categories():
    with app.app_context():
        # Create categories if they don't exist
        print("Setting up categories...")
        for i, name in enumerate(DEFAULT_CATEGORIES):
            existing = Category.query.filter_by(name=name).first()
            if not existing:
                category = Category(name=name, display_order=i, is_active=True)
                db.session.add(category)
                print(f"  Created category: {name}")
            else:
                print(f"  Category exists: {name}")

        db.session.commit()

        # Auto-assign services to categories based on name patterns
        print("\nAssigning services to categories...")
        categories = {c.name: c for c in Category.query.all()}
        services = Service.query.filter_by(is_active=True, category_id=None).all()

        assigned = 0
        for service in services:
            service_name_lower = service.name.lower()

            # Check each category's patterns
            for cat_name, patterns in CATEGORY_MAPPINGS.items():
                if cat_name in categories:
                    for pattern in patterns:
                        if pattern.lower() in service_name_lower:
                            service.category_id = categories[cat_name].id
                            print(f"  {service.name} -> {cat_name}")
                            assigned += 1
                            break
                    if service.category_id:
                        break

        db.session.commit()
        print(f"\n✓ Done! Assigned {assigned} services to categories.")

        # Show uncategorized count
        uncategorized = Service.query.filter_by(is_active=True, category_id=None).count()
        if uncategorized > 0:
            print(f"  {uncategorized} services still uncategorized (can be assigned in admin)")


if __name__ == '__main__':
    setup_categories()
