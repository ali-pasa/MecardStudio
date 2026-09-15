from django.core.management.base import BaseCommand
from api.models import CardCategory

class Command(BaseCommand):
    help = "Seeds the CardCategory lookup table"

    def handle(self, *args, **options):
        categories = [
            ("Digital Business Card", "digital_business_card",
             ["full_name", "job_title", "company_name", "phone", "email", "qr_code"], "1.75:1"),
            ("Digital ID Card", "digital_id_card",
             ["photo", "full_name", "id_number", "department", "qr_code", "valid_until"], "1.6:1"),
            ("Digital Visitor Pass", "digital_visitor_pass",
             ["visitor_name", "host_name", "visit_date", "qr_code", "valid_until"], "1.6:1"),
            ("Digital Membership Card", "digital_membership_card",
             ["member_name", "membership_id", "tier", "qr_code", "valid_until"], "1.6:1"),
            ("Digital Health Card", "digital_health_card",
             ["patient_name", "patient_id", "blood_group", "emergency_contact", "qr_code"], "1.6:1"),
            ("Digital Insurance Card", "digital_insurance_card",
             ["policy_holder_name", "policy_number", "provider_name", "valid_until", "qr_code"], "1.6:1"),
            ("Digital Emergency QR", "digital_emergency_qr",
             ["full_name", "emergency_contact", "medical_notes", "qr_code"], "1:1"),
            ("Digital Parking Tag", "digital_parking_tag",
             ["vehicle_number", "owner_name", "valid_until", "qr_code"], "1.6:1"),
            ("Custom Digital Card", "custom_digital_card", ["qr_code"], "1.6:1"),
        ]

        for name, slug, fields, ratio in categories:
            obj, created = CardCategory.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "required_fields": fields, "default_aspect_ratio": ratio},
            )
            status = "created" if created else "already exists"
            self.stdout.write(f"{name}: {status}")