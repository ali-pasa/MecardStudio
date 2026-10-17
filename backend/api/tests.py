import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Card, CardCategory, Company, CompanyBrandPreference, Role
from .services.card_generation import render_mock_card_template, render_preview_html
from .services.extraction import (
	extract_brand_colors,
	extract_company_name,
	extract_company_info_with_ai,
)
from bs4 import BeautifulSoup


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


class GeneratedCardSelectionTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_superuser(
			username="card-selection-admin",
			email="card-selection@example.com",
			password="Test-Password-482!",
		)
		self.company = Company.objects.create(
			user=self.user,
			website_url="https://example.com",
			company_name="Example Company",
		)
		self.category = CardCategory.objects.create(
			name="Selection test",
			slug="selection-test",
			required_fields=[],
		)
		self.client.force_login(self.user)

	def test_card_list_has_preview_action_and_preview_api_returns_rendered_card(self):
		card = Card.objects.create(
			company=self.company,
			category=self.category,
			name="Preview this card",
			html_content="<main><h1>{{company_name}}</h1></main>",
			public_slug="preview-this-card",
		)

		list_response = self.client.get("/admin/api/card/")
		self.assertEqual(list_response.status_code, 200)
		self.assertContains(list_response, 'class="card-preview-trigger"')
		self.assertContains(list_response, 'class="admin-page-heading"')
		self.assertContains(list_response, "Add card")
		self.assertContains(list_response, f'data-preview-url="/admin/api/card/{card.pk}/preview/"')

		preview_response = self.client.get(f"/admin/api/card/{card.pk}/preview/")
		self.assertEqual(preview_response.status_code, 200)
		self.assertTrue(preview_response["Content-Type"].startswith("text/html"))
		self.assertEqual(preview_response["X-Frame-Options"], "SAMEORIGIN")
		self.assertContains(preview_response, "Example Company")

	def test_generation_saves_only_the_previews_the_user_selects(self):
		previous_card = Card.objects.create(
			company=self.company,
			category=self.category,
			name="Previously selected card",
			html_content="<main>Previous design</main>",
			public_slug="previous-selection-card",
			is_active=True,
		)
		generation_data = {
			"company_id": self.company.pk,
			"category_slug": self.category.slug,
			"name": "ID Card",
			"variant_count": 2,
		}
		with patch(
			"api.views.generate_card_template",
			side_effect=["<main>First option</main>", "<main>Second option</main>"],
		) as generate_template:
			response = self.client.post(
				"/api/cards/generate/",
				data=json.dumps(generation_data),
				content_type="application/json",
			)

		self.assertEqual(response.status_code, 200)
		variants = response.json()["variants"]
		self.assertEqual(len(variants), 2)
		self.assertEqual(
			len({call.kwargs["design_direction"] for call in generate_template.call_args_list}),
			2,
		)
		self.assertEqual(Card.objects.count(), 1)

		save_response = self.client.post(
			"/api/cards/save-generated/",
			data=json.dumps({
				"preview_tokens": [
					variants[0]["preview_token"],
					variants[1]["preview_token"],
				],
			}),
			content_type="application/json",
		)

		self.assertEqual(save_response.status_code, 201)
		self.assertEqual(Card.objects.count(), 3)
		saved_cards = list(Card.objects.exclude(pk=previous_card.pk).order_by("name"))
		self.assertEqual(len(saved_cards), 2)
		self.assertIn("First option", saved_cards[0].html_content)
		self.assertIn("Second option", saved_cards[1].html_content)
		for saved_card in saved_cards:
			with self.subTest(card=saved_card.name):
				self.assertIn("generated-card-fallback", saved_card.html_content)
				self.assertTrue(saved_card.is_active)
		previous_card.refresh_from_db()
		self.assertFalse(previous_card.is_active)
		self.assertEqual(
			Card.objects.filter(
				company=self.company,
				category=self.category,
				is_active=True,
			).count(),
			2,
		)

	def test_vertical_orientation_is_applied_and_saved_for_preview(self):
		generation_data = {
			"company_id": self.company.pk,
			"category_slug": self.category.slug,
			"name": "Vertical ID Card",
			"variant_count": 1,
			"orientation": "vertical",
		}
		with patch(
			"api.views.generate_card_template",
			return_value="<html><head><style>.card { width: 480px; height: 300px; }</style></head><body><main class='card'>Vertical</main></body></html>",
		) as generate_template:
			response = self.client.post(
				"/api/cards/generate/",
				data=json.dumps(generation_data),
				content_type="application/json",
			)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			generate_template.call_args.kwargs["category"].default_aspect_ratio,
			"1:1.6",
		)
		variant = response.json()["variants"][0]
		self.assertEqual(variant["orientation"], "vertical")
		self.assertEqual(variant["aspect_ratio"], "1:1.6")
		self.assertIn("height: 768px !important", variant["preview_html"])
		self.assertIn(".card.vertical .portrait", variant["preview_html"])

		save_response = self.client.post(
			"/api/cards/save-generated/",
			data=json.dumps({"preview_tokens": [variant["preview_token"]]}),
			content_type="application/json",
		)
		self.assertEqual(save_response.status_code, 201)
		saved_card = Card.objects.get(name="Vertical ID Card (Variant 1)")
		self.assertEqual(saved_card.meta_data["orientation"], "vertical")
		self.assertEqual(saved_card.meta_data["aspect_ratio"], "1:1.6")

		admin_preview = self.client.get(f"/admin/api/card/{saved_card.pk}/preview/")
		self.assertEqual(admin_preview.status_code, 200)
		self.assertContains(admin_preview, "height: 768px !important")

	def test_generation_rejects_unknown_card_orientation(self):
		response = self.client.post(
			"/api/cards/generate/",
			data=json.dumps({
				"company_id": self.company.pk,
				"category_slug": self.category.slug,
				"orientation": "diagonal",
			}),
			content_type="application/json",
		)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.json()["error"], "orientation must be horizontal or vertical.")

	def test_unstyled_generated_markup_gets_a_card_preview_design(self):
		preview_html = render_preview_html(
			"<main><h1>{{company_name}}</h1></main>",
			self.category,
			self.company,
		)

		self.assertIn("generated-card-fallback", preview_html)
		self.assertIn("linear-gradient", preview_html)
		self.assertIn("Example Company", preview_html)

	def test_local_card_templates_use_distinct_branded_directions(self):
		first = render_mock_card_template(
			self.company,
			None,
			self.category,
			"editorial",
		)
		second = render_mock_card_template(
			self.company,
			None,
			self.category,
			"dark",
		)

		self.assertIn('class="card editorial"', first)
		self.assertIn('class="card dark"', second)
		self.assertIn("--brand: #1f6f8b", first)
		self.assertNotEqual(first, second)

	def test_vertical_local_template_uses_compact_balanced_content(self):
		vertical_category = CardCategory(
			name="Vertical card",
			slug="vertical-card",
			required_fields=["photo", "full_name", "id_number", "qr_code"],
			default_aspect_ratio="1:1.6",
		)
		template = render_mock_card_template(
			self.company,
			None,
			vertical_category,
			"editorial",
		)

		self.assertIn('class="card editorial vertical"', template)
		self.assertIn(".card.vertical .portrait", template)
		self.assertIn("height: 142px", template)
		self.assertIn("<h1>{{full_name}}</h1>", template)
		self.assertIn('class="vertical-footer"', template)
		self.assertNotIn("h1 { margin: auto 0", template)
		preview = render_preview_html(template, vertical_category, self.company)
		self.assertIn("data:image/svg+xml;base64,", preview)
		self.assertNotIn("placehold.co", preview)


class CompanyNameExtractionTests(TestCase):
	def test_company_name_uses_site_metadata_and_title_fallbacks(self):
		cases = [
			(
				'<meta property="og:site_name" content="Acme Studio"><title>Home</title>',
				"https://example.com",
				"Acme Studio",
			),
			(
				"<title>Northwind Design | Official site</title>",
				"https://northwind.example",
				"Northwind Design",
			),
			(
				"<h1>Brightline Collective</h1>",
				"https://brightline.example",
				"Brightline Collective",
			),
			(
				"<p>Welcome</p>",
				"https://www.blue-sky.example",
				"Blue sky",
			),
		]
		for html, website_url, expected in cases:
			with self.subTest(website_url=website_url):
				self.assertEqual(
					extract_company_name(BeautifulSoup(html, "html.parser"), website_url),
					expected,
				)

	@patch("api.services.extraction.settings.GEMINI_API_KEY", "")
	def test_missing_ai_key_uses_website_name_instead_of_shared_mock(self):
		info = extract_company_info_with_ai(
			"Northwind creates useful tools.",
			"Tools for thoughtful teams.",
			"Northwind",
		)

		self.assertEqual(info["company_name"], "Northwind")
		self.assertNotIn("mock data", info["company_name"])

	def test_brand_palette_is_extracted_from_metadata_and_css(self):
		soup = BeautifulSoup(
			"""
			<meta name="theme-color" content="#123456">
			<style>:root { --brand-accent: rgb(240, 160, 32); --secondary-color: #334455; }</style>
			""",
			"html.parser",
		)

		colors = extract_brand_colors(soup, "https://brand.example", None)

		self.assertEqual(colors["primary_color"], "#123456")
		self.assertEqual(colors["secondary_color"], "#334455")
		self.assertEqual(colors["accent_color"], "#f0a020")
