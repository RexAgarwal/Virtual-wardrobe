import shutil
import tempfile
from datetime import date
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image

from .models import Item, Outfit, PackItem, PlannedOutfit, Trip

MEDIA = tempfile.mkdtemp()


def png(name='x.png'):
    buf = BytesIO()
    Image.new('RGB', (40, 50), (200, 180, 160)).save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=MEDIA, WARDROBE_INVITE_CODE='')
class AccountIsolation(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.ann = User.objects.create_user('ann', password='pw-ann-12345')
        self.bo = User.objects.create_user('bo', password='pw-bo-12345')
        self.item = Item(owner=self.ann, name='Ann Tee', category='top', color='White')
        self.item.photo.save('t.png', png())
        self.outfit = Outfit.objects.create(owner=self.ann, name='Ann Look')
        self.outfit.items.add(self.item)
        self.trip = Trip.objects.create(owner=self.ann, name='Ann Trip', start=date(2026, 11, 1), end=date(2026, 11, 3))
        self.pack = PackItem.objects.create(trip=self.trip, item=self.item)
        PlannedOutfit.objects.create(owner=self.ann, date=date(2026, 11, 2), outfit=self.outfit)

    def as_(self, user):
        self.client.force_login(user)
        return self.client

    def test_anonymous_goes_to_login(self):
        for url in ('/', '/outfits/', '/plan/', '/trips/', '/fit-check/', '/about/', self.item.photo.url):
            r = self.client.get(url)
            self.assertRedirects(r, f'/login/?next={url}', fetch_redirect_response=False, msg_prefix=url)

    def test_login_and_signup_pages_are_public(self):
        self.assertEqual(self.client.get('/login/').status_code, 200)
        self.assertEqual(self.client.get('/signup/').status_code, 200)

    def test_signup_creates_account_and_signs_in(self):
        r = self.client.post('/signup/', {'username': 'cy', 'password1': 'a-long-pass-99', 'password2': 'a-long-pass-99'})
        self.assertRedirects(r, '/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(User.objects.get(username='cy').items.count(), 0)

    @override_settings(WARDROBE_INVITE_CODE='sesame')
    def test_signup_needs_invite_code_when_set(self):
        data = {'username': 'cy', 'password1': 'a-long-pass-99', 'password2': 'a-long-pass-99'}
        self.assertEqual(self.client.post('/signup/', {**data, 'invite': 'wrong'}).status_code, 200)
        self.assertFalse(User.objects.filter(username='cy').exists())
        self.client.post('/signup/', {**data, 'invite': 'sesame'})
        self.assertTrue(User.objects.filter(username='cy').exists())

    def test_login_works_and_wrong_password_fails(self):
        self.assertEqual(self.client.post('/login/', {'username': 'ann', 'password': 'nope'}).status_code, 200)
        r = self.client.post('/login/', {'username': 'ann', 'password': 'pw-ann-12345'})
        self.assertEqual(r.status_code, 302)

    def test_demo_account_cannot_log_in(self):
        demo = User.objects.create(username='demo', password='!')
        self.assertFalse(demo.has_usable_password())

    def test_logout_is_post_only(self):
        c = self.as_(self.ann)
        self.assertEqual(c.get('/logout/').status_code, 405)
        self.assertEqual(c.post('/logout/').status_code, 302)
        self.assertEqual(c.get('/').status_code, 302)

    def test_other_user_cannot_see_or_touch_pieces(self):
        c = self.as_(self.bo)
        self.assertNotContains(c.get('/'), 'Ann Tee')
        for url in (f'/items/{self.item.pk}/', f'/items/{self.item.pk}/edit/'):
            self.assertEqual(c.get(url).status_code, 404, url)
        self.assertEqual(c.post(f'/items/{self.item.pk}/delete/').status_code, 404)
        self.assertTrue(Item.objects.filter(pk=self.item.pk).exists())

    def test_photos_are_private(self):
        self.assertEqual(self.as_(self.ann).get(self.item.photo.url).status_code, 200)
        self.assertEqual(self.as_(self.bo).get(self.item.photo.url).status_code, 404)

    def test_outfits_are_private_and_cannot_use_foreign_pieces(self):
        c = self.as_(self.bo)
        self.assertNotContains(c.get('/outfits/'), 'Ann Look')
        self.assertEqual(c.get(f'/outfits/{self.outfit.pk}/').status_code, 404)
        self.assertEqual(c.post(f'/outfits/{self.outfit.pk}/wore/').status_code, 404)
        r = c.post('/outfits/new/', {'name': 'Sneaky', 'occasion': 'everyday', 'items': [self.item.pk]})
        self.assertEqual(r.status_code, 200)  # form rejected
        self.assertFalse(Outfit.objects.filter(name='Sneaky').exists())

    def test_planner_is_private(self):
        c = self.as_(self.bo)
        self.assertNotContains(c.get('/plan/?start=2026-10-26'), 'Ann Look')
        self.assertEqual(c.post('/plan/set/', {'date': '2026-11-03', 'outfit': self.outfit.pk}).status_code, 404)
        self.assertFalse(PlannedOutfit.objects.filter(owner=self.bo).exists())
        c.post('/plan/set/', {'date': '2026-11-02', 'outfit': ''})  # must not clear Ann's plan
        self.assertTrue(PlannedOutfit.objects.filter(owner=self.ann, date=date(2026, 11, 2)).exists())

    def test_trips_are_private(self):
        c = self.as_(self.bo)
        self.assertNotContains(c.get('/trips/'), 'Ann Trip')
        self.assertEqual(c.get(f'/trips/{self.trip.pk}/').status_code, 404)
        self.assertEqual(c.post(f'/trips/{self.trip.pk}/toggle/{self.item.pk}/').status_code, 404)
        self.assertEqual(c.post(f'/trips/{self.trip.pk}/delete/').status_code, 404)
        self.assertTrue(Trip.objects.filter(pk=self.trip.pk).exists())

    def test_both_users_can_plan_the_same_day(self):
        mine = Outfit.objects.create(owner=self.bo, name='Bo Look')
        self.as_(self.bo).post('/plan/set/', {'date': '2026-11-02', 'outfit': mine.pk})
        self.assertEqual(PlannedOutfit.objects.filter(date=date(2026, 11, 2)).count(), 2)

    def test_samples_go_only_to_the_requesting_user(self):
        self.as_(self.bo).post('/samples/')
        self.assertEqual(self.bo.items.count(), 15)
        self.assertEqual(self.ann.items.count(), 1)
        self.as_(self.bo).post('/samples/')  # repeat is harmless
        self.assertEqual(self.bo.items.count(), 15)

    def test_style_me_only_uses_own_pieces(self):
        self.as_(self.bo).post('/samples/')
        self.assertNotContains(self.as_(self.bo).get('/outfits/generate/'), 'Ann Tee')

    def test_fitcheck_token_belongs_to_one_session(self):
        r = self.as_(self.bo).post('/fit-check/add/', {'token': 'a' * 32, 'keep': ['0']})
        self.assertRedirects(r, '/fit-check/', fetch_redirect_response=False)
        self.assertEqual(self.bo.items.count(), 0)


@override_settings(MEDIA_ROOT=MEDIA)
class StyleMe(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sam', password='pw-sam-12345')
        self.client.force_login(self.user)

    def add(self, name, category, color='White'):
        item = Item(owner=self.user, name=name, category=category, color=color)
        item.photo.save('t.png', png())
        return item

    def test_tops_and_accessories_still_get_looks_and_a_hint(self):
        self.add('Tee', 'top')
        self.add('Watch', 'accessory', 'Gold')
        r = self.client.get('/outfits/generate/')
        self.assertContains(r, 'Tee')
        self.assertContains(r, 'a bottom or a dress')

    def test_complete_wardrobe_has_no_hint(self):
        for n, c in (('Tee', 'top'), ('Jeans', 'bottom'), ('Sneakers', 'shoes')):
            self.add(n, c, 'Black')
        self.assertNotContains(self.client.get('/outfits/generate/'), 'for complete outfits')

    def test_accessories_alone_explain_what_to_add(self):
        self.add('Watch', 'accessory')
        self.assertContains(self.client.get('/outfits/generate/'), 'Add a few clothes first')


def fake_cutout(jobs):
    img = Image.new('RGBA', (30, 40), (10, 20, 30, 255))
    img.paste((0, 0, 0, 0), (0, 0, 10, 10))  # a transparent corner, like a real cut-out
    return [img.copy() for _ in jobs]


@override_settings(MEDIA_ROOT=MEDIA)
class PictureChoice(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('pia', password='pw-pia-12345')
        self.other = User.objects.create_user('quin', password='pw-quin-12345')
        self.client.force_login(self.user)
        patcher = mock.patch.multiple('closet.views.cutout', available=lambda: True, cut_out=fake_cutout)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add_piece(self):
        return self.client.post('/items/new/', {
            'name': 'Tee', 'photo': png(), 'category': 'top', 'season': 'all', 'formality': 2, 'status': 'active'})

    def test_adding_a_piece_offers_the_choice_and_keeps_the_original_by_default(self):
        r = self.add_piece()
        item = Item.objects.get(name='Tee')
        self.assertRedirects(r, f'/items/{item.pk}/picture/', fetch_redirect_response=False)
        self.assertTrue(item.other_photo)
        self.assertFalse(item.photo_is_cutout)
        self.assertContains(self.client.get(f'/items/{item.pk}/picture/'), 'Use the cut-out')

    def test_choosing_the_cutout_swaps_the_pictures_and_can_swap_back(self):
        self.add_piece()
        item = Item.objects.get(name='Tee')
        original, cut = item.photo.name, item.other_photo.name
        self.client.post(f'/items/{item.pk}/picture/', {'use': 'other'})
        item.refresh_from_db()
        self.assertEqual((item.photo.name, item.other_photo.name, item.photo_is_cutout), (cut, original, True))
        self.client.post(f'/items/{item.pk}/picture/', {'use': 'other'})
        item.refresh_from_db()
        self.assertEqual((item.photo.name, item.photo_is_cutout), (original, False))

    def test_cutouts_keep_transparency(self):
        self.add_piece()
        item = Item.objects.get(name='Tee')
        alt = Image.open(item.other_photo.path)
        self.assertEqual(alt.format, 'WEBP')
        self.assertIn('A', alt.getbands())

    def test_both_pictures_are_private_to_the_owner(self):
        self.add_piece()
        item = Item.objects.get(name='Tee')
        self.assertEqual(self.client.get(item.other_photo.url).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(item.other_photo.url).status_code, 404)
        self.assertEqual(self.client.get(f'/items/{item.pk}/picture/').status_code, 404)
        self.assertEqual(self.client.post(f'/items/{item.pk}/cutout/').status_code, 404)

    def test_failed_cutout_just_saves_the_piece(self):
        with mock.patch('closet.views.cutout.cut_out', lambda jobs: [None] * len(jobs)):
            r = self.add_piece()
        item = Item.objects.get(name='Tee')
        self.assertRedirects(r, f'/items/{item.pk}/', fetch_redirect_response=False)
        self.assertFalse(item.other_photo)

    def test_make_cutout_later_from_the_piece_page(self):
        with mock.patch('closet.views.cutout.cut_out', lambda jobs: [None] * len(jobs)):
            self.add_piece()
        item = Item.objects.get(name='Tee')
        self.assertContains(self.client.get(f'/items/{item.pk}/'), 'Make a cut-out')
        r = self.client.post(f'/items/{item.pk}/cutout/')
        self.assertRedirects(r, f'/items/{item.pk}/picture/', fetch_redirect_response=False)

    def test_removing_a_piece_removes_both_files(self):
        self.add_piece()
        item = Item.objects.get(name='Tee')
        paths = [item.photo.path, item.other_photo.path]
        self.client.post(f'/items/{item.pk}/delete/')
        import os
        self.assertFalse(any(os.path.exists(p) for p in paths))
