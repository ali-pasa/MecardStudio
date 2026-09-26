import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Card, CardCategory, Company, CompanyBrandPreference, Role


class MasterAuditFieldTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_superuser(
			username="audit-admin",
			email="audit@example.com",
			password="test-password-123",
		)

	def test_master_models_have_active_and_audit_defaults(self):
		company = Company.objects.create(
			user=self.user,
			website_url="https://example.com",
		)
		category = CardCategory.objects.create(name="Audit", slug="audit")
		records = [
			self.user,
			Role.objects.create(name="Audited"),
			company,
			CompanyBrandPreference.objects.create(company=company),
			category,
			Card.objects.create(
				company=company,
				category=category,
				name="Audit card",
				html_content="<main>Audit</main>",
				public_slug="audit-card",
			),
		]

		for record in records:
			with self.subTest(model=record._meta.label):
				self.assertTrue(record.is_active)
				self.assertEqual(record.meta_data, {})
				self.assertIsNotNone(record.created_at)
				self.assertIsNotNone(record.updated_at)
				self.assertIsNone(record.ip_address)
				self.assertIsNone(record.created_by)
				self.assertIsNone(record.updated_by)

	def test_role_admin_captures_audit_actor_and_ip_on_create_and_update(self):
		self.client.force_login(self.user)
		add_url = "/admin/api/role/add/"
		add_data = {
			"name": "Audited role",
			"is_active": "on",
			"meta_data": json.dumps({"source": "test"}),
		}

		response = self.client.post(add_url, add_data, REMOTE_ADDR="192.0.2.10")
		self.assertEqual(response.status_code, 302)
		role = Role.objects.get(name="Audited role")
		self.assertEqual(role.created_by, self.user)
		self.assertEqual(role.updated_by, self.user)
		self.assertEqual(role.ip_address, "192.0.2.10")
		self.assertEqual(role.meta_data, {"source": "test"})
		self.assertTrue(role.is_active)

		response = self.client.post(
			f"/admin/api/role/{role.pk}/change/",
			{
				**add_data,
				"name": "Updated audited role",
				"meta_data": "",
			},
			REMOTE_ADDR="192.0.2.11",
		)
		self.assertEqual(response.status_code, 302)
		role.refresh_from_db()
		self.assertEqual(role.created_by, self.user)
		self.assertEqual(role.updated_by, self.user)
		self.assertEqual(role.ip_address, "192.0.2.11")
		self.assertEqual(role.name, "Updated audited role")
		self.assertIsNone(role.meta_data)

	def test_user_admin_add_form_saves_active_and_audit_fields(self):
		self.client.force_login(self.user)
		response = self.client.get("/admin/api/user/add/")
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'name="is_active"')
		self.assertContains(response, 'name="meta_data"')

		response = self.client.post(
			"/admin/api/user/add/",
			{
				"username": "audited-user",
				"password1": "Another-Strong-Pass-482!",
				"password2": "Another-Strong-Pass-482!",
				"is_active": "on",
				"meta_data": '{"source":"admin"}',
			},
			REMOTE_ADDR="192.0.2.12",
		)
		self.assertEqual(response.status_code, 302)
		created_user = get_user_model().objects.get(username="audited-user")
		self.assertTrue(created_user.is_active)
		self.assertEqual(created_user.meta_data, {"source": "admin"})
		self.assertEqual(created_user.created_by, self.user)
		self.assertEqual(created_user.updated_by, self.user)
		self.assertEqual(created_user.ip_address, "192.0.2.12")
