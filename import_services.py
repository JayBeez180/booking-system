#!/usr/bin/env python3
"""
Import services from CSV/TSV data into the booking system database.
"""

import sys
import os
import re

# Add the parent directory to path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import db, Service

# Services data (tab-separated)
services_data = """Ear Package £80 (for 1 person) age 16+	80	60	Piercing package including THREE piercings for one person. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Lobe age £30 16+	30	45	Single lobe piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Lobe x2 £50 age 16+	50	45	Pair of lobe piercings. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Helix £37 age 16+	37	45	Helix piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Conch £37 age 16+	37	45	Conch piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Flat £37 age 16+	37	45	Flat piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Daith £40 age 16+	40	45	Daith piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Tragus £37 age 16+	37	45	Tragus piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Anti Tragus £40 age 18+	40	45	Anti-tragus piercing. 18+ only. Please bring photo ID.	Ear
Rook £40 age 16+	40	45	Rook piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Industrial £47 age 18+	47	60	Industrial piercing. 18+ only. Please bring photo ID.	Ear
Forward Helix £37 age 16+	37	45	Forward helix piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Ear
Teen Helix £37 age 13+	37	45	Helix piercing for ages 13+. Parent/guardian with matching ID required.	Under 16s
Teen Lobes (pair) 12-16 years	67	60	Pair of lobe piercings for ages 12-16. Price includes piercing fee and jewellery. Parent/guardian with matching ID required.	Under 16s
Teen Single Lobe 12-16 years	35	45	Single lobe piercing for ages 12-16. Price includes piercing fee and jewellery. Parent/guardian with matching ID required.	Under 16s
Children's Single Lobe 7-12 years	35	45	Single lobe piercing for ages 7-12. Price includes piercing fee and jewellery. Parent/guardian with matching ID required. Not available on Fridays.	Under 16s
Children's Lobes (pair) 7-12 years	67	60	Pair of lobe piercings for ages 7-12. Price includes piercing fee and jewellery. Parent/guardian with matching ID required. Not available on Fridays.	Under 16s
Labret £40 age 18+	40	45	Lip piercing - can be placed anywhere around the lips. 18+ only. Please bring photo ID.	Lips
Labret x2 £60 age 18+	60	60	Double lip piercing - can be placed anywhere around the lips. 18+ only. Please bring photo ID.	Lips
Vertical Labret £40 age 18+	40	45	Vertical lip piercing on the lower lip. 18+ only. Please bring photo ID.	Lips
Philtrum (Medusa) £40 age 18+	40	45	Lip piercing placed in the centre above the lip. 18+ only. Please bring photo ID.	Lips
Nostril £37 age 16+	37	45	Nose piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Nose
Double/Paired Nostril £65 age 16+	65	60	Double nose piercing (opposite sides). Please bring photo ID. Under 18s need parent/guardian with matching ID.	Nose
Septum £45 age 16+	45	45	Septum piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Nose
Both Nipples £77 age 18+	77	60	Both nipples pierced. 18+ only. Please bring photo ID.	Body
Single Nipple £47 age 18+	47	45	Single nipple piercing. 18+ only. Please bring photo ID.	Body
Navel £47 age 16+	47	45	Navel/belly button piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Body
Bridge £47 age 18+	47	60	Bridge piercing (anatomy dependent). 18+ only. Please bring photo ID.	Face
Eyebrow £37 age 16+	37	45	Eyebrow piercing. Please bring photo ID. Under 18s need parent/guardian with matching ID.	Face
Quick Anatomy Check	10	15	Not sure you can get the piercing you want? Quick assessment of your anatomy and answer any questions.	Consultation
Ear Mapping/Consultation	25	45	Non-piercing appointment. We'll discuss your ear plans, draw placements, and explore jewellery options. Fee deducted from fitting total.	Consultation
Full Ear Consultation	50	60	Non-piercing appointment. Full consultation for your perfect ear design - jewellery selection, anatomy check, style options and pricing. For 3+ jewellery changes. Fee deducted from fitting total. Ages 16+.	Consultation
MRI/Medical Removal/Replacement	10	15	Assistance removing jewellery for medical procedures. Please bring your own bioflex jewellery if needed.	Service
Jewellery Downsize (3+ areas)	30	30	Bar shrink for multiple piercings. Once swelling has gone down, shorter bars aid healing. £10 per labret.	Service
Help - I've Had a Swell!	0	30	For existing clients only. If you're struggling with inflammation after a piercing done by us, we can change to a longer bar if necessary.	Service
Piercing Health Check	5	15	General piercing check-up only. Does not include jewellery. Please include concerns in notes.	Service
Navel Jewellery Downsize	10	15	Bar shrink for navel piercing. Once swelling has gone down, shorter bar aids healing.	Service
Eyebrow Jewellery Downsize	10	15	Bar shrink for eyebrow piercing. Once swelling has gone down, shorter bar aids healing.	Service
Lip Jewellery Downsize	10	15	Bar shrink for lip piercing. Once swelling has gone down, shorter bar aids healing.	Service
Nose Jewellery Downsize	10	15	Bar shrink for nose piercing. Once swelling has gone down, shorter bar aids healing.	Service
Nipple Jewellery Downsize	10	30	Bar shrink for nipple piercing.	Service
Jewellery Change	10	30	Jewellery upgrades from our extensive range. £10 appointment fee, additional charge for jewellery.	Service
Ear Jewellery Downsize (up to 2 areas)	10	15	Bar shrink for ear piercings. Once swelling has gone down, shorter bars aid healing. £10 per labret.	Service
Custom Chain Fitting	35	60	Custom chain fitting for healed piercings only.	Other"""

def import_services():
    with app.app_context():
        # Check for existing services
        existing_count = Service.query.count()
        if existing_count > 0:
            print(f"Note: Database already has {existing_count} services. Adding new ones...")

        imported = 0
        skipped = 0

        for line in services_data.strip().split('\n'):
            parts = line.split('\t')
            if len(parts) >= 4:
                name = parts[0].strip()
                price = float(parts[1]) if parts[1] else 0.0
                duration = int(parts[2]) if parts[2] else 30
                description = parts[3].strip() if len(parts) > 3 else ''
                category = parts[4].strip() if len(parts) > 4 else ''

                # Check if service with this name already exists
                existing = Service.query.filter_by(name=name).first()
                if existing:
                    print(f"Skipped (exists): {name}")
                    skipped += 1
                    continue

                # Create new service
                service = Service(
                    name=name,
                    price=price,
                    duration_minutes=duration,
                    description=description,
                    is_active=True
                )
                db.session.add(service)
                imported += 1
                print(f"Imported: {name} - £{price:.2f} ({duration} mins)")

        db.session.commit()
        print(f"\n✓ Import complete! {imported} services imported, {skipped} skipped.")

if __name__ == '__main__':
    import_services()
