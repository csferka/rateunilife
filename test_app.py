import unittest

from app import create_app
from config import TestingConfig
from models import Post, Report, Tag, User, db


class RateMyUniLifeTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestingConfig)
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def register_user(self, username='student1', email='student1@example.com', password='password123'):
        return self.client.post(
            '/auth/register',
            data={
                'username': username,
                'email': email,
                'password': password,
                'confirm_password': password,
            },
            follow_redirects=True,
        )

    def login_user(self, username='student1', password='password123'):
        return self.client.post(
            '/auth/login',
            data={'username': username, 'password': password},
            follow_redirects=True,
        )

    def create_post(self, title='My Course Review'):
        return self.client.post(
            '/post/new',
            data={
                'title': title,
                'category': 'course',
                'university': 'Webster University in Tashkent',
                'tags': 'webster, cs',
                'content': 'This course has a heavy workload but useful labs.',
                'is_anonymous': 'on',
            },
            follow_redirects=True,
        )

    def test_registration_login_and_first_user_admin(self):
        response = self.register_user()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Registration successful', response.data)

        with self.app.app_context():
            user = User.query.filter_by(username='student1').first()
            self.assertIsNotNone(user)
            self.assertTrue(user.is_admin)

        response = self.login_user()
        self.assertIn(b'Welcome back, student1', response.data)

    def test_post_comment_vote_and_report_flow(self):
        self.register_user()
        self.login_user()

        response = self.create_post()
        self.assertIn(b'My Course Review', response.data)

        with self.app.app_context():
            post = Post.query.filter_by(title='My Course Review').first()
            self.assertIsNotNone(post)
            post_id = post.id

        response = self.client.post(
            f'/post/{post_id}/comment',
            data={'content': 'Very accurate review.'},
            follow_redirects=True,
        )
        self.assertIn(b'Comment added successfully', response.data)

        response = self.client.post(f'/post/{post_id}/vote', data={'vote_type': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['vote_count'], 1)
        self.assertEqual(response.json['user_vote'], 1)

        response = self.client.post(
            f'/post/{post_id}/report',
            data={'reason': 'Needs moderator review'},
            follow_redirects=True,
        )
        self.assertIn(b'admin will review', response.data.lower())

        with self.app.app_context():
            report = Report.query.filter_by(post_id=post_id).first()
            self.assertIsNotNone(report)
            self.assertEqual(report.status, 'pending')

    def test_admin_can_review_reports(self):
        self.register_user()
        self.login_user()
        self.create_post(title='Campus Review')

        with self.app.app_context():
            post = Post.query.filter_by(title='Campus Review').first()
            report = Report(reporter_id=1, post_id=post.id, reason='Spam content')
            db.session.add(report)
            db.session.commit()
            report_id = report.id

        response = self.client.post(
            f'/admin/report/{report_id}/resolve',
            data={'action': 'dismiss'},
            follow_redirects=True,
        )
        self.assertIn(b'Report has been processed', response.data)

        with self.app.app_context():
            report = db.session.get(Report, report_id)
            self.assertEqual(report.status, 'dismissed')

    def test_long_university_slug_is_saved_as_tag(self):
        self.register_user()
        self.login_user()

        response = self.client.post(
            '/post/new',
            data={
                'title': 'Long University Name Review',
                'category': 'general',
                'university': 'Tashkent University of Information Technologies named after Muhammad al-Khwarizmi',
                'tags': 'admission, campus',
                'content': 'Posting this should still work even when the university slug is long.',
                'is_anonymous': 'on',
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Your post has been published', response.data)

        with self.app.app_context():
            post = Post.query.filter_by(title='Long University Name Review').first()
            self.assertIsNotNone(post)
            university_tags = [tag.name for tag in post.tags if tag.name.startswith('uni-')]
            self.assertEqual(len(university_tags), 1)
            self.assertGreater(len(university_tags[0]), 50)
            self.assertIsNotNone(Tag.query.filter_by(name=university_tags[0]).first())

    def test_join_community_updates_membership_state(self):
        self.register_user()
        self.login_user()

        response = self.client.post(
            '/university/wiut/join',
            data={},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'You joined the Wiut community', response.data)
        self.assertIn(b'1 Community Members', response.data)
        self.assertIn(b'Joined Community', response.data)

        with self.app.app_context():
            user = User.query.filter_by(username='student1').first()
            self.assertEqual(user.university_slug, 'wiut')
            self.assertTrue(user.has_joined_community('wiut'))

    def test_joining_another_community_keeps_existing_memberships(self):
        self.register_user()
        self.login_user()

        first_join = self.client.post(
            '/university/wiut/join',
            data={},
            follow_redirects=True,
        )
        self.assertEqual(first_join.status_code, 200)

        second_join = self.client.post(
            '/university/wsau/join',
            data={},
            follow_redirects=True,
        )

        self.assertEqual(second_join.status_code, 200)
        self.assertIn(b'You joined the Wsau community', second_join.data)
        self.assertIn(b'Joined Community', second_join.data)

        wiut_feed = self.client.get('/university/wiut')
        self.assertEqual(wiut_feed.status_code, 200)
        self.assertIn(b'Joined Community', wiut_feed.data)
        self.assertIn(b'1 Community Members', wiut_feed.data)

        with self.app.app_context():
            user = User.query.filter_by(username='student1').first()
            joined_communities = {tag.name for tag in user.communities}
            self.assertIn('uni-wiut', joined_communities)
            self.assertIn('uni-wsau', joined_communities)
            self.assertEqual(user.university_slug, 'wiut')

    def test_navbar_communities_only_show_joined_communities_for_member(self):
        self.register_user()
        self.login_user()
        self.create_post(title='Webster Review')

        self.client.post(
            '/university/wiut/join',
            data={},
            follow_redirects=True,
        )

        response = self.client.get('/', follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="/university/wiut"', response.data)
        self.assertNotIn(b'href="/university/webster-university-in-tashkent"', response.data)


if __name__ == '__main__':
    unittest.main()
