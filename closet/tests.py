import shutil
import tempfile
from datetime import date
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest import mock

from django.test import Client, TestCase, override_settings
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

    def test_redoing_the_cutout_replaces_only_the_cutout_and_keeps_the_original(self):
        self.add_piece()
        item = Item.objects.get(name='Tee')
        original = item.photo.name
        self.client.post(f'/items/{item.pk}/cutout/')
        item.refresh_from_db()
        self.assertEqual(item.photo.name, original)
        self.assertTrue(item.other_photo)
        self.client.post(f'/items/{item.pk}/picture/', {'use': 'other'})  # now the cut-out is in use
        item.refresh_from_db()
        kept_original = item.other_photo.name
        self.client.post(f'/items/{item.pk}/cutout/')
        item.refresh_from_db()
        self.assertEqual(item.other_photo.name, kept_original)
        self.assertTrue(item.photo_is_cutout)


@override_settings(MEDIA_ROOT=MEDIA)
class OutfitView(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ola', password='pw-ola-12345')
        self.client.force_login(self.user)

    def piece(self, name, category, cutout):
        item = Item(owner=self.user, name=name, category=category, photo_is_cutout=cutout)
        item.photo.save('t.png', png())
        return item

    def outfit(self, *items):
        o = Outfit.objects.create(owner=self.user, name='Look')
        o.items.set(items)
        return o

    def test_cutouts_are_stacked_and_plain_photos_are_listed_separately(self):
        o = self.outfit(self.piece('Tee', 'top', True), self.piece('Jeans', 'bottom', True),
                        self.piece('Loafers', 'shoes', False))
        r = self.client.get(f'/outfits/{o.pk}/')
        self.assertContains(r, 'class="board"')
        self.assertEqual([i.name for i in r.context['board']['centre']], ['Tee', 'Jeans'])
        self.assertEqual([i.name for i in r.context['board']['left_out']], ['Loafers'])
        self.assertContains(r, 'aren&rsquo;t shown here')

    def test_order_is_top_bottom_shoes_and_layers_sit_beside(self):
        o = self.outfit(self.piece('Boots', 'shoes', True), self.piece('Coat', 'outerwear', True),
                        self.piece('Skirt', 'bottom', True), self.piece('Tee', 'top', True),
                        self.piece('Watch', 'accessory', True))
        b = self.client.get(f'/outfits/{o.pk}/').context['board']
        self.assertEqual([i.name for i in b['centre']], ['Tee', 'Skirt', 'Boots'])
        self.assertEqual([i.name for i in b['left']], ['Coat'])
        self.assertEqual([i.name for i in b['right']], ['Watch'])

    def test_a_dress_takes_the_top_slot(self):
        o = self.outfit(self.piece('Dress', 'dress', True), self.piece('Tee', 'top', True))
        self.assertEqual(len(self.client.get(f'/outfits/{o.pk}/').context['board']['centre']), 1)

    def test_no_cutouts_means_no_board_and_a_hint(self):
        o = self.outfit(self.piece('Tee', 'top', False))
        r = self.client.get(f'/outfits/{o.pk}/')
        self.assertNotContains(r, 'class="board"')
        self.assertContains(r, 'Make cut-outs for these pieces')


@override_settings(MEDIA_ROOT=MEDIA, WARDROBE_BETA_USERS=['Himanshu'], WARDROBE_FEATURES={'tryon': 'beta'})
class TryOnRollout(TestCase):
    def setUp(self):
        self.him = User.objects.create_user('himanshu', password='pw-him-12345')   # different case on purpose
        self.boss = User.objects.create_user('boss', password='pw-boss-12345', is_staff=True)
        self.root = User.objects.create_user('root', password='pw-root-12345', is_superuser=True)
        self.pal = User.objects.create_user('pal', password='pw-pal-12345')

    def status(self, user, url='/try-on/'):
        self.client.force_login(user)
        return self.client.get(url).status_code

    def test_beta_users_and_admins_get_it_everyone_else_gets_a_404(self):
        self.assertEqual([self.status(u) for u in (self.him, self.boss, self.root)], [200, 200, 200])
        self.assertEqual(self.status(self.pal), 404)

    def test_the_menu_link_only_shows_for_people_who_have_it(self):
        self.client.force_login(self.him)
        self.assertContains(self.client.get('/about/'), 'Try on <span class="beta">')
        self.client.force_login(self.pal)
        self.assertNotContains(self.client.get('/about/'), 'Try on <span class="beta">')

    def test_signed_out_people_cannot_reach_it(self):
        self.assertEqual(self.client.get('/try-on/').status_code, 302)

    def test_rolling_out_to_everyone_or_switching_off(self):
        with override_settings(WARDROBE_FEATURES={'tryon': 'all'}):
            self.assertEqual(self.status(self.pal), 200)
        with override_settings(WARDROBE_FEATURES={'tryon': 'off'}):
            self.assertEqual(self.status(self.root), 404)

    def test_someone_without_the_feature_cannot_start_a_job_either(self):
        o = Outfit.objects.create(owner=self.pal, name='x')
        self.client.force_login(self.pal)
        self.assertEqual(self.client.post(f'/outfits/{o.pk}/try-on/').status_code, 404)


@override_settings(MEDIA_ROOT=MEDIA, WARDROBE_BETA_USERS=['Himanshu'], WARDROBE_FEATURES={'tryon': 'beta'})
class TryOnFlow(TestCase):
    def setUp(self):
        from .models import TryOn  # noqa: F401
        self.me = User.objects.create_user('himanshu', password='pw-him-12345')
        self.root = User.objects.create_user('root', password='pw-root-12345', is_superuser=True)
        self.client.force_login(self.me)
        self.started = []
        for patcher in (mock.patch('closet.views.tryon.start', lambda job: self.started.append(job.pk)),
                        mock.patch('closet.views.tryon.available', lambda: True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.top = self.piece('Tee', 'top')
        self.bottom = self.piece('Jeans', 'bottom')
        self.outfit = Outfit.objects.create(owner=self.me, name='Look')
        self.outfit.items.set([self.top, self.bottom, self.piece('Shoes', 'shoes')])

    def piece(self, name, category):
        item = Item(owner=self.me, name=name, category=category)
        item.photo.save('t.png', png())
        return item

    def add_photo(self):
        return self.client.post('/try-on/', {'photo': png('me.png')})

    def test_photo_is_saved_resized_and_private(self):
        self.add_photo()
        photo = self.me.tryon_photo
        self.assertTrue(photo.photo.name.startswith('tryon/people/'))
        self.assertEqual(self.client.get(photo.photo.url).status_code, 200)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(photo.photo.url).status_code, 404)

    def test_starting_needs_a_photo_first(self):
        r = self.client.post(f'/outfits/{self.outfit.pk}/try-on/')
        self.assertRedirects(r, '/try-on/', fetch_redirect_response=False)
        self.assertEqual(self.started, [])

    def test_starting_makes_a_job_and_runs_it(self):
        from .models import TryOn
        self.add_photo()
        r = self.client.post(f'/outfits/{self.outfit.pk}/try-on/')
        job = TryOn.objects.get()
        self.assertRedirects(r, f'/try-on/{job.pk}/', fetch_redirect_response=False)
        self.assertEqual(self.started, [job.pk])
        page = self.client.get(f'/try-on/{job.pk}/')
        self.assertContains(page, 'http-equiv="refresh"')

    def test_jobs_are_private(self):
        from .models import TryOn
        self.add_photo()
        self.client.post(f'/outfits/{self.outfit.pk}/try-on/')
        job = TryOn.objects.get()
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(f'/try-on/{job.pk}/').status_code, 404)
        self.assertEqual(self.client.post(f'/try-on/{job.pk}/delete/').status_code, 404)

    def test_dresses_and_pairs_pick_the_right_garments(self):
        from . import tryon
        self.assertEqual([(i.name, k) for i, k in tryon.garments_for(self.outfit)], [('Tee', 'upper'), ('Jeans', 'lower')])
        self.outfit.items.add(self.piece('Gown', 'dress'))
        self.assertEqual([(i.name, k) for i, k in tryon.garments_for(self.outfit)], [('Gown', 'overall')])

    def test_an_outfit_with_nothing_to_wear_is_refused(self):
        self.add_photo()
        only_shoes = Outfit.objects.create(owner=self.me, name='Feet')
        only_shoes.items.set([i for i in self.outfit.items.all() if i.category == 'shoes'])
        self.client.post(f'/outfits/{only_shoes.pk}/try-on/')
        self.assertEqual(self.started, [])

    def test_a_missing_model_is_reported_not_crashed(self):
        from . import tryon
        from .models import TryOn
        self.add_photo()
        job = TryOn.objects.create(owner=self.me, outfit=self.outfit)
        with mock.patch('closet.tryon.available', lambda: False):
            try:
                tryon._generate(job)
            except RuntimeError as e:
                self.assertIn('not installed', str(e))
            else:
                self.fail('should have raised')


@override_settings(MEDIA_ROOT=MEDIA, WARDROBE_BETA_USERS=['Himanshu'], WARDROBE_FEATURES={'perfumes': 'beta'})
class Perfumes(TestCase):
    def setUp(self):
        from .models import Perfume  # noqa: F401
        self.me = User.objects.create_user('himanshu', password='pw-him-12345')
        self.boss = User.objects.create_user('boss', password='pw-boss-12345', is_staff=True)
        self.pal = User.objects.create_user('pal', password='pw-pal-12345')
        self.client.force_login(self.me)

    def add(self, **extra):
        data = {'name': 'Sauvage', 'brand': 'Dior', 'concentration': 'edt', 'season': 'all', 'occasion': 'everyday',
                'rating': 4, 'status': 'in_use', 'notes': 'bergamot, pepper, ambroxan', **extra}
        return self.client.post('/perfumes/new/', data)

    def test_only_beta_people_and_admins_see_it(self):
        statuses = {}
        for user in (self.me, self.boss, self.pal):
            self.client.force_login(user)
            statuses[user.username] = self.client.get('/perfumes/').status_code
        self.assertEqual(statuses, {'himanshu': 200, 'boss': 200, 'pal': 404})
        self.client.force_login(self.pal)
        self.assertEqual(self.add().status_code, 404)
        self.assertNotContains(self.client.get('/about/'), 'Perfumes <span')

    def test_menu_link_shows_for_beta_people(self):
        self.assertContains(self.client.get('/about/'), 'Perfumes <span class="beta">')

    def test_add_view_edit_and_remove(self):
        from .models import Perfume
        r = self.add()
        p = Perfume.objects.get()
        self.assertRedirects(r, f'/perfumes/{p.pk}/', fetch_redirect_response=False)
        page = self.client.get(f'/perfumes/{p.pk}/')
        self.assertContains(page, 'Sauvage')
        self.assertContains(page, 'ambroxan')
        self.assertEqual(p.stars, '★★★★☆')
        self.client.post(f'/perfumes/{p.pk}/edit/', {'name': 'Sauvage Elixir', 'brand': 'Dior', 'concentration': 'parfum',
                                                    'season': 'winter', 'occasion': 'evening', 'rating': 5, 'status': 'in_use'})
        p.refresh_from_db()
        self.assertEqual((p.name, p.concentration), ('Sauvage Elixir', 'parfum'))
        self.client.post(f'/perfumes/{p.pk}/delete/')
        self.assertFalse(Perfume.objects.exists())

    def test_one_persons_shelf_is_invisible_to_another(self):
        from .models import Perfume
        self.add()
        p = Perfume.objects.get()
        self.client.force_login(self.boss)
        self.assertEqual(list(self.client.get('/perfumes/').context['perfumes']), [])
        for method, url in (('get', f'/perfumes/{p.pk}/'), ('get', f'/perfumes/{p.pk}/edit/'), ('post', f'/perfumes/{p.pk}/delete/')):
            self.assertEqual(getattr(self.client, method)(url).status_code, 404, url)
        self.assertTrue(Perfume.objects.filter(pk=p.pk).exists())

    def test_bottle_photos_are_optional_and_private(self):
        from .models import Perfume
        self.add(photo=png('bottle.png'))
        p = Perfume.objects.get()
        self.assertTrue(p.photo.name.endswith('.webp'))
        self.assertEqual(self.client.get(p.photo.url).status_code, 200)
        self.client.force_login(self.boss)
        self.assertEqual(self.client.get(p.photo.url).status_code, 404)

    def test_rating_is_clamped_and_filters_work(self):
        from .models import Perfume
        self.add(name='Citrus One', family='citrus', season='summer', notes='lemon')
        self.add(name='Wood Two', family='woody', season='winter', notes='cedar', status='wishlist')
        self.assertEqual(Perfume.objects.count(), 2)
        names = lambda query: [p.name for p in self.client.get('/perfumes/' + query).context['perfumes']]
        self.assertEqual(names('?family=citrus'), ['Citrus One'])
        self.assertEqual(names('?q=cedar'), ['Wood Two'])
        self.assertEqual(names('?status=in_use'), ['Citrus One'])
        self.assertEqual(names('?season=summer'), ['Citrus One'])
        self.add(name='Too High', rating=9)  # a rating above 5 is trimmed to 5, never stored as 9
        self.assertEqual(Perfume.objects.get(name='Too High').rating, 5)
        self.assertFalse(Perfume.objects.filter(rating__gt=5).exists())


class LinkPreview(TestCase):
    def test_reads_schema_org_product_data(self):
        from . import linkpreview as lp
        html = '''<html><head><title>Shop</title><script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[{"@type":"WebSite"},{"@type":"Product","name":"Linen Shirt",
         "image":["/img/a.jpg","/img/b.jpg"],"offers":[{"@type":"Offer","price":"1,299.00","priceCurrency":"inr"}]}]}
        </script></head></html>'''
        info = lp.parse(html, 'https://www.shop.example/p/1')
        self.assertEqual((info['name'], info['price'], info['currency'], info['image_url'], info['site']),
                         ('Linen Shirt', '1299.00', 'INR', 'https://www.shop.example/img/a.jpg', 'www.shop.example'))

    def test_falls_back_to_open_graph_tags(self):
        from . import linkpreview as lp
        html = '''<head><meta property="og:title" content="Black   Jeans"><meta property="og:image" content="https://cdn.example/j.jpg">
        <meta property="product:price:amount" content="49,90"><meta property="product:price:currency" content="eur"></head>'''
        info = lp.parse(html, 'https://x.example/')
        self.assertEqual((info['name'], info['price'], info['currency']), ('Black Jeans', '49.90', 'EUR'))

    def test_price_formats(self):
        from .linkpreview import _number
        cases = {'1,299.00': '1299.00', '₹ 1299': '1299.00', '1.299,50': '1299.50', '49,90': '49.90', '2,499': '2499.00',
                 1299: '1299.00', None: '', 'free': ''}
        for raw, want in cases.items():
            self.assertEqual(_number(raw), want, raw)

    def test_amazon_style_titles_are_trimmed(self):
        from . import linkpreview as lp
        info = lp.parse('<title>ADRO Cotton Polo for Men : Amazon.in: Fashion</title>', 'https://www.amazon.in/dp/X')
        self.assertEqual(info['name'], 'ADRO Cotton Polo for Men')

    def test_private_and_odd_addresses_are_refused(self):
        from . import linkpreview as lp
        for url in ('http://127.0.0.1/', 'http://localhost:8000/', 'http://10.0.0.5/', 'http://192.168.1.1/x',
                    'http://169.254.169.254/latest/meta-data/', 'http://[::1]/', 'file:///etc/passwd', 'ftp://93.184.216.34/',
                    'javascript:alert(1)', 'not a url', ''):
            with self.assertRaises(lp.LinkError, msg=url):
                lp.check_url(url)
        self.assertEqual(lp.check_url('https://93.184.216.34/page').hostname, '93.184.216.34')

    def test_a_redirect_into_the_private_network_is_refused(self):
        import urllib.error
        from email.message import Message
        from . import linkpreview as lp
        headers = Message()
        headers['Location'] = 'http://192.168.0.10/admin'

        def fake_open(self, request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 302, 'Found', headers, None)

        with mock.patch('urllib.request.OpenerDirector.open', fake_open):
            with self.assertRaises(lp.LinkError):
                lp.fetch('https://93.184.216.34/start')


@override_settings(MEDIA_ROOT=MEDIA, WARDROBE_BETA_USERS=['Himanshu'], WARDROBE_FEATURES={'watchlist': 'beta'})
class Watchlist(TestCase):
    def setUp(self):
        self.me = User.objects.create_user('himanshu', password='pw-him-12345')
        self.boss = User.objects.create_user('boss', password='pw-boss-12345', is_staff=True)
        self.pal = User.objects.create_user('pal', password='pw-pal-12345')
        self.client.force_login(self.me)

    def save(self, **extra):
        data = {'name': 'Linen Shirt', 'url': 'https://www.shop.example/p/1', 'kind': 'top', 'price': '1299',
                'currency': 'inr', 'priority': 2, 'status': 'watching', **extra}
        return self.client.post('/watchlist/new/', data)

    def test_only_beta_people_and_admins(self):
        codes = {}
        for user in (self.me, self.boss, self.pal):
            self.client.force_login(user)
            codes[user.username] = self.client.get('/watchlist/').status_code
        self.assertEqual(codes, {'himanshu': 200, 'boss': 200, 'pal': 404})
        self.client.force_login(self.pal)
        self.assertEqual(self.client.post('/watchlist/new/', {'fetch_url': 'https://x.example'}).status_code, 404)

    def test_add_by_hand_with_a_price_and_site_from_the_link(self):
        from .models import WatchItem
        self.save()
        w = WatchItem.objects.get()
        self.assertEqual((w.site, w.currency, w.price_label), ('shop.example', 'INR', '₹1,299'))

    def test_link_autofill_fills_the_form_and_the_picture_is_saved_on_submit(self):
        from . import linkpreview
        from .models import WatchItem
        info = {'name': 'Linen Shirt', 'price': '1299.00', 'currency': 'INR', 'image_url': 'https://cdn.shop.example/a.jpg', 'site': 's'}
        with mock.patch('closet.views.linkpreview.fetch', return_value=info):
            page = self.client.post('/watchlist/new/', {'fetch_url': 'https://www.shop.example/p/1'})
        self.assertContains(page, 'value="Linen Shirt"')
        self.assertContains(page, 'value="https://cdn.shop.example/a.jpg"')
        with mock.patch('closet.views.linkpreview.fetch_image', return_value=png().read()):
            self.save(image_url='https://cdn.shop.example/a.jpg')
        w = WatchItem.objects.get()
        self.assertTrue(w.photo.name.endswith('.webp'))

    def test_a_blocked_shop_falls_back_to_typing_it_in_and_keeps_the_link(self):
        from . import linkpreview
        with mock.patch('closet.views.linkpreview.fetch', side_effect=linkpreview.LinkError('That shop did not let me read the page.')):
            page = self.client.post('/watchlist/new/', {'fetch_url': 'https://www.myntra.example/p'})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'value="https://www.myntra.example/p"')
        self.assertContains(page, 'did not let me read the page')

    def test_a_bad_picture_link_does_not_stop_the_item_being_saved(self):
        from . import linkpreview
        from .models import WatchItem
        with mock.patch('closet.views.linkpreview.fetch_image', side_effect=linkpreview.LinkError('no')):
            self.save(image_url='http://127.0.0.1/secret.png')
        self.assertFalse(WatchItem.objects.get().photo)

    def test_it_is_private_including_the_picture(self):
        from .models import WatchItem
        self.save(photo=png('shirt.png'))
        w = WatchItem.objects.get()
        self.assertEqual(self.client.get(w.photo.url).status_code, 200)
        self.client.force_login(self.boss)
        self.assertEqual(list(self.client.get('/watchlist/?status=all').context['items']), [])
        for method, url in (('get', f'/watchlist/{w.pk}/'), ('get', f'/watchlist/{w.pk}/edit/'),
                            ('post', f'/watchlist/{w.pk}/delete/'), ('post', f'/watchlist/{w.pk}/bought/'), ('get', w.photo.url)):
            self.assertEqual(getattr(self.client, method)(url).status_code, 404, url)
        self.assertTrue(WatchItem.objects.filter(pk=w.pk).exists())

    def test_totals_are_kept_per_currency(self):
        self.save(name='A', price='1000', currency='INR')
        self.save(name='B', price='500', currency='inr')
        self.save(name='C', price='40', currency='usd')
        self.save(name='D', price='999', currency='INR', status='bought')  # not counted: already bought
        totals = self.client.get('/watchlist/').context['totals']
        self.assertEqual(sorted(totals), ['$40', '₹1,500'])

    def test_bought_clothes_move_into_the_wardrobe_with_picture_and_price(self):
        from .models import WatchItem
        self.save(photo=png('shirt.png'))
        w = WatchItem.objects.get()
        r = self.client.post(f'/watchlist/{w.pk}/bought/')
        item = Item.objects.get(owner=self.me)
        self.assertRedirects(r, f'/items/{item.pk}/edit/', fetch_redirect_response=False)
        self.assertEqual((item.name, item.category, str(item.price)), ('Linen Shirt', 'top', '1299.00'))
        self.assertTrue(item.photo)
        w.refresh_from_db()
        self.assertEqual(w.status, 'bought')

    def test_bought_perfume_goes_to_the_perfume_shelf_and_other_things_just_get_marked(self):
        from .models import Perfume, WatchItem
        with override_settings(WARDROBE_FEATURES={'watchlist': 'beta', 'perfumes': 'beta'}):
            self.save(name='Sauvage', kind='perfume', photo=png('p.png'))
            self.client.post(f'/watchlist/{WatchItem.objects.get(name="Sauvage").pk}/bought/')
            self.assertEqual(Perfume.objects.get(owner=self.me).name, 'Sauvage')
        self.save(name='Gift card', kind='other')
        gift = WatchItem.objects.get(name='Gift card')
        self.client.post(f'/watchlist/{gift.pk}/bought/')
        gift.refresh_from_db()
        self.assertEqual(gift.status, 'bought')
        self.assertEqual(Item.objects.filter(owner=self.me).count(), 0)


@override_settings(MEDIA_ROOT=MEDIA, WARDROBE_BETA_USERS=['Himanshu'], WARDROBE_FEATURES={'watchlist': 'beta'})
class BrowserSaveButton(TestCase):
    def setUp(self):
        from .models import ImportToken
        self.me = User.objects.create_user('himanshu', password='pw-him-12345')
        self.pal = User.objects.create_user('pal', password='pw-pal-12345')
        self.token = ImportToken.reset(self.me).token
        patcher = mock.patch('closet.views.linkpreview.fetch_image', side_effect=lambda url: png().read())
        self.fetch_image = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, client=None, **extra):
        data = {'token': self.token, 'url': 'https://www.myntra.com/tshirts/x/1/buy', 'name': 'Striped Hoodie',
                'price': '\u20b9 1,299.00', 'currency': '', 'image': 'https://assets.shop.example/t.jpg', **extra}
        return (client or Client()).post('/watchlist/import/', data)

    def test_the_button_saves_straight_to_the_watchlist_with_picture_and_price(self):
        from .models import WatchItem
        r = self.post()  # a fresh, signed-out client, like a post arriving from another website
        w = WatchItem.objects.get()
        self.assertRedirects(r, f'/watchlist/{w.pk}/', fetch_redirect_response=False)
        self.assertEqual((w.owner, w.name, str(w.price), w.currency, w.kind, w.site, w.status),
                         (self.me, 'Striped Hoodie', '1299.00', 'INR', 'top', 'myntra.com', 'watching'))
        self.assertTrue(w.photo.name.endswith('.webp'))
        self.client.force_login(self.me)
        listing = self.client.get('/watchlist/')
        self.assertEqual([i.name for i in listing.context['items']], ['Striped Hoodie'])
        self.assertContains(listing, w.photo.url)
        self.assertContains(listing, '\u20b91,299')

    def test_only_one_picture_file_is_stored_not_a_raw_copy_too(self):
        import os
        from .models import WatchItem
        self.post()
        folder = os.path.dirname(WatchItem.objects.get().photo.path)
        self.assertEqual([f for f in os.listdir(folder) if not f.endswith('.webp')], [])

    def test_a_missing_or_unreadable_picture_still_saves_the_item(self):
        from . import linkpreview
        from .models import WatchItem
        self.fetch_image.side_effect = linkpreview.LinkError('blocked')
        self.post()
        w = WatchItem.objects.get()
        self.assertFalse(w.photo)
        for junk in (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', b'<html>Access denied</html>', b''):
            self.fetch_image.side_effect = lambda url, junk=junk: junk
            self.post(url=f'https://shop.example/{len(junk)}')
        self.assertEqual(WatchItem.objects.count(), 4)
        self.assertFalse(any(i.photo for i in WatchItem.objects.all()))

    def test_it_works_without_a_csrf_token_but_only_with_a_valid_secret(self):
        from .models import WatchItem
        self.assertEqual(self.post(client=Client(enforce_csrf_checks=True)).status_code, 302)
        for bad in ('', 'nope', self.token[:-1], self.token + 'x'):
            self.assertEqual(self.post(token=bad).status_code, 403, bad)
        self.assertEqual(WatchItem.objects.count(), 1)

    def test_a_secret_for_someone_without_the_feature_is_refused(self):
        from .models import ImportToken, WatchItem
        self.assertEqual(self.post(token=ImportToken.reset(self.pal).token).status_code, 403)
        self.assertFalse(WatchItem.objects.exists())

    def test_a_new_button_stops_the_old_one(self):
        from .models import ImportToken
        old = self.token
        ImportToken.reset(self.me)
        self.assertEqual(self.post(token=old).status_code, 403)

    def test_tapping_twice_does_not_make_two_entries(self):
        from .models import WatchItem
        self.post()
        self.post()
        self.assertEqual(WatchItem.objects.count(), 1)
        self.post(url='https://www.myntra.com/another/page')
        self.assertEqual(WatchItem.objects.count(), 2)

    def test_the_item_belongs_to_the_secrets_owner_and_stays_private(self):
        from .models import WatchItem
        self.post()
        w = WatchItem.objects.get()
        self.client.force_login(self.pal)
        self.assertEqual(self.client.get(f'/watchlist/{w.pk}/').status_code, 404)

    def test_odd_input_is_cleaned_not_trusted(self):
        from .models import WatchItem
        self.post(name='x' * 500, url='javascript:alert(1)', image='data:text/html,<script>', price='free', currency='toolong')
        w = WatchItem.objects.get()
        self.assertEqual((len(w.name), w.url, bool(w.photo), w.price, w.currency), (120, '', False, None, 'TOO'))
        self.fetch_image.assert_not_called()

    def test_names_are_tidied_and_kinds_guessed(self):
        from .models import WatchItem
        cases = {'ADRO Premium Polo : Amazon.in: Clothing': ('ADRO Premium Polo', 'top'),
                 'Slim Fit Jeans for Men': ('Slim Fit Jeans for Men', 'bottom'),
                 'Nike Air Max Sneakers': ('Nike Air Max Sneakers', 'shoes'),
                 'Dior Sauvage Eau de Toilette 100ml': ('Dior Sauvage Eau de Toilette 100ml', 'perfume'),
                 'Hooded Puffer Jacket': ('Hooded Puffer Jacket', 'outerwear'),
                 'Mystery Thing': ('Mystery Thing', 'other')}
        for i, (raw, (name, kind)) in enumerate(cases.items()):
            self.post(name=raw, url=f'https://shop.example/{i}')
            w = WatchItem.objects.get(url=f'https://shop.example/{i}')
            self.assertEqual((w.name, w.kind), (name, kind), raw)

    def test_a_page_with_nothing_readable_still_saves_something_to_fix(self):
        from .models import WatchItem
        self.post(name='', price='', image='')
        w = WatchItem.objects.get()
        self.assertEqual((w.name, w.price, bool(w.photo)), ('Untitled item', None, False))

    def test_setup_page_has_a_working_personal_button(self):
        self.client.force_login(self.me)
        page = self.client.get('/watchlist/button/')
        self.assertContains(page, 'javascript:')
        self.assertContains(page, self.token)
        self.assertContains(page, 'testserver')
        self.client.force_login(self.pal)
        self.assertEqual(self.client.get('/watchlist/button/').status_code, 404)

    def test_resetting_makes_a_different_secret(self):
        from .models import ImportToken
        self.client.force_login(self.me)
        self.client.post('/watchlist/button/')
        self.assertNotEqual(ImportToken.objects.get(owner=self.me).token, self.token)

    # Older saves that were left waiting as drafts still show up and can be finished
    def draft(self):
        from .models import WatchDraft
        return WatchDraft.objects.create(owner=self.me, name='Old Hoodie', price='999.00', currency='INR',
                                         image_url='https://cdn.shop.example/h.jpg', url='https://shop.example/h')

    def test_leftover_drafts_show_as_picture_cards_with_a_price(self):
        d = self.draft()
        self.client.force_login(self.me)
        page = self.client.get('/watchlist/')
        self.assertContains(page, 'Waiting for you to confirm')
        self.assertContains(page, 'src="https://cdn.shop.example/h.jpg"')
        self.assertContains(page, 'INR 999.00')
        self.assertNotContains(page, 'Your watchlist is empty')
        self.assertContains(page, f'/watchlist/draft/{d.pk}/')

    def test_the_draft_review_form_posts_to_the_page_that_saves_it(self):
        import re
        from .models import WatchDraft, WatchItem
        d = self.draft()
        self.client.force_login(self.me)
        html = self.client.get(f'/watchlist/draft/{d.pk}/').content.decode()
        form_tag = re.search(r'<form method="post" enctype="multipart/form-data"[^>]*>', html).group(0)
        self.assertIn('action="/watchlist/new/"', form_tag)
        fields = {m.group(1): m.group(2) for m in re.finditer(r'<input type="hidden" name="(draft|image_url)"[^>]*value="([^"]*)"', html)}
        r = self.client.post('/watchlist/new/', {**fields, 'name': 'Hoodie', 'url': d.url, 'kind': 'top', 'price': '999',
                                                 'currency': 'INR', 'priority': 2, 'status': 'watching'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(WatchItem.objects.get().photo)
        self.assertFalse(WatchDraft.objects.exists())

    def test_drafts_are_private_and_can_be_discarded(self):
        from .models import WatchDraft
        d = self.draft()
        self.client.force_login(self.pal)
        for method, url in (('get', f'/watchlist/draft/{d.pk}/'), ('post', f'/watchlist/draft/{d.pk}/discard/')):
            self.assertEqual(getattr(self.client, method)(url).status_code, 404)
        self.client.force_login(self.me)
        self.client.post(f'/watchlist/draft/{d.pk}/discard/')
        self.assertFalse(WatchDraft.objects.exists())
