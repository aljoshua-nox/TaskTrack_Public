import logging
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import ActivityLog, Group, Task, TaskComment


def form_deadline(dt):
    return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')


# A fast hasher keeps the suite quick; production hashing is unaffected.
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class TaskTrackTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Views log every action and denial; keep test output readable.
        logging.disable(logging.WARNING)
        cls.addClassCleanup(logging.disable, logging.NOTSET)

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='owner', password='pass12345')
        cls.member = User.objects.create_user(username='member', password='pass12345')
        cls.member_two = User.objects.create_user(username='member_two', password='pass12345')
        cls.outsider = User.objects.create_user(username='outsider', password='pass12345')

        cls.group = Group.objects.create(
            name='Alpha Team',
            description='Group for testing',
            created_by=cls.owner,
        )
        cls.group.members.add(cls.owner, cls.member, cls.member_two)

        cls.task = Task.objects.create(
            title='Initial Task',
            description='Baseline task',
            group=cls.group,
            assigned_to=cls.member,
            created_by=cls.owner,
            deadline=timezone.now() + timedelta(days=2),
            status='PENDING',
        )

    def make_task(self, title, assigned_to=None, group=None, days=3, **fields):
        return Task.objects.create(
            title=title,
            group=group or self.group,
            assigned_to=assigned_to or self.member,
            created_by=(group or self.group).created_by,
            deadline=timezone.now() + timedelta(days=days),
            **fields,
        )

    def make_overdue(self, task):
        # Bypass Task.save so the deadline can be in the past.
        Task.objects.filter(id=task.id).update(
            deadline=timezone.now() - timedelta(days=1),
            status='OVERDUE',
        )
        task.refresh_from_db()
        return task


class CoreViewTests(TaskTrackTestCase):

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_group_generates_unique_join_code(self):
        another_group = Group.objects.create(
            name='Alpha Team',
            description='Same name, different code',
            created_by=self.owner,
        )
        self.assertEqual(len(self.group.join_code), 8)
        self.assertEqual(len(another_group.join_code), 8)
        self.assertNotEqual(self.group.join_code, another_group.join_code)

    def test_dashboard_shows_user_group_and_task_stats(self):
        self.client.login(username='member', password='pass12345')
        Task.objects.create(
            title='Done Task',
            description='Completed work',
            group=self.group,
            assigned_to=self.member,
            created_by=self.owner,
            deadline=timezone.now() + timedelta(days=1),
            status='COMPLETED',
        )

        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['groups_count'], 1)
        self.assertEqual(response.context['total_assigned'], 2)
        self.assertEqual(response.context['total_completed'], 1)

    def test_group_detail_blocks_non_member(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.get(reverse('core:group_detail', args=[self.group.id]))
        self.assertRedirects(response, reverse('core:group_list'))

    def test_group_detail_allows_member(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.get(reverse('core:group_detail', args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['group'], self.group)

    def test_group_detail_includes_group_activity_history(self):
        older = ActivityLog.objects.create(
            user=self.owner,
            group=self.group,
            action='GROUP_CREATED',
            description='older entry',
        )
        newer = ActivityLog.objects.create(
            user=self.member,
            group=self.group,
            task=self.task,
            action='TASK_UPDATED',
            description='newer entry',
        )

        # Ensure deterministic ordering for this test.
        older_ts = timezone.make_aware(parse_datetime('2026-01-01T00:00:00'))
        newer_ts = timezone.make_aware(parse_datetime('2026-01-01T01:00:00'))
        ActivityLog.objects.filter(id=older.id).update(timestamp=older_ts)
        ActivityLog.objects.filter(id=newer.id).update(timestamp=newer_ts)

        self.client.login(username='owner', password='pass12345')
        response = self.client.get(reverse('core:group_detail', args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('group_activities', response.context)
        activity_descriptions = [entry.description for entry in response.context['group_activities']]
        self.assertEqual(activity_descriptions[0], 'newer entry')
        self.assertEqual(activity_descriptions[1], 'older entry')

    def test_group_detail_contribution_tracker_uses_completed_and_activity_shares(self):
        self.task.status = 'COMPLETED'
        self.task.completed_at = timezone.now()
        self.task.save()
        Task.objects.create(
            title='Second Completed Task',
            description='Done by member_two',
            group=self.group,
            assigned_to=self.member_two,
            created_by=self.owner,
            deadline=timezone.now() + timedelta(days=3),
            status='COMPLETED',
            completed_at=timezone.now(),
        )

        ActivityLog.objects.create(
            user=self.owner,
            group=self.group,
            action='GROUP_CREATED',
            description='owner created group',
        )
        ActivityLog.objects.create(
            user=self.member,
            group=self.group,
            task=self.task,
            action='TASK_UPDATED',
            description='member updated their task',
        )
        ActivityLog.objects.create(
            user=self.member,
            group=self.group,
            task=self.task,
            action='TASK_COMPLETED',
            description='member completed their task',
        )

        self.client.login(username='owner', password='pass12345')
        response = self.client.get(reverse('core:group_detail', args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_completed_member_tasks'], 2)
        self.assertEqual(response.context['total_group_activities'], 3)

        contributions = {
            row['user'].username: row for row in response.context['member_contributions']
        }
        self.assertAlmostEqual(contributions['member']['contribution_share'], 50.0)
        self.assertAlmostEqual(contributions['member_two']['contribution_share'], 50.0)
        self.assertEqual(contributions['member']['activity_count'], 2)
        self.assertAlmostEqual(contributions['member']['activity_share'], 66.6666, places=3)
        self.assertTrue(contributions['owner']['is_leader'])

    def test_task_create_blocks_non_member(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.post(
            reverse('core:task_create', args=[self.group.id]),
            {
                'title': 'Unauthorized Task',
                'description': 'Should not be created',
                'assigned_to': self.member.id,
                'deadline': (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
                'file_link': '',
            },
        )
        self.assertRedirects(response, reverse('core:group_list'))
        self.assertFalse(Task.objects.filter(title='Unauthorized Task').exists())

    def test_task_create_blocks_non_leader_member(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:task_create', args=[self.group.id]),
            {
                'title': 'Member Task',
                'description': 'Should not be created',
                'assigned_to': self.member.id,
                'deadline': (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
                'file_link': '',
            },
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertFalse(Task.objects.filter(title='Member Task').exists())

    def test_task_create_by_leader_creates_task_and_activity(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(
            reverse('core:task_create', args=[self.group.id]),
            {
                'title': 'New Group Task',
                'description': 'Created by owner',
                'assigned_to': self.member.id,
                'deadline': (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
                'file_link': 'https://example.com/file',
            },
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        created_task = Task.objects.get(title='New Group Task')
        self.assertEqual(created_task.group, self.group)
        self.assertTrue(
            ActivityLog.objects.filter(
                task=created_task,
                action='TASK_CREATED',
            ).exists()
        )

    def test_task_edit_blocks_non_member(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.get(reverse('core:task_edit', args=[self.task.id]))
        self.assertRedirects(response, reverse('core:dashboard'))

    def test_task_edit_blocks_non_leader_member(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.get(reverse('core:task_edit', args=[self.task.id]))
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))

    def test_task_edit_by_leader_updates_fields_and_logs_activity(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(
            reverse('core:task_edit', args=[self.task.id]),
            {
                'title': 'Edited Task Title',
                'description': 'Updated description',
                'assigned_to': self.member_two.id,
                'deadline': (timezone.now() + timedelta(days=5)).strftime('%Y-%m-%dT%H:%M'),
                'file_link': 'https://example.com/edited-file',
            },
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))

        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Edited Task Title')
        self.assertEqual(self.task.description, 'Updated description')
        self.assertEqual(self.task.assigned_to, self.member_two)
        self.assertEqual(self.task.file_link, 'https://example.com/edited-file')
        self.assertTrue(
            ActivityLog.objects.filter(
                task=self.task,
                user=self.owner,
                action='TASK_UPDATED',
                description__icontains='edited task',
            ).exists()
        )

    def test_update_task_status_blocks_member_not_assigned_and_not_leader(self):
        self.client.login(username='member_two', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'COMPLETED'},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'PENDING')

    def test_task_detail_shows_full_progress_for_completed_task(self):
        self.task.status = 'COMPLETED'
        self.task.completed_at = timezone.now()
        self.task.save()

        self.client.login(username='member', password='pass12345')
        response = self.client.get(reverse('core:task_detail', args=[self.task.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['task_progress_percentage'], 100)
        self.assertContains(response, 'style="width: 100%;"')
        self.assertContains(response, '100% Complete')

    def test_update_task_status_by_assigned_member_works(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'COMPLETED', 'file_link': 'https://example.com/submission'},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'COMPLETED')
        self.assertEqual(self.task.file_link, 'https://example.com/submission')
        self.assertIsNotNone(self.task.completed_at)

    def test_update_task_status_by_leader_works(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'IN_PROGRESS'},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'IN_PROGRESS')

    def test_rollback_from_completed_requires_comment(self):
        self.task.status = 'COMPLETED'
        self.task.completed_at = timezone.now()
        self.task.save()
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'PENDING', 'rollback_comment': ''},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'COMPLETED')

    def test_rollback_from_completed_with_comment_is_logged(self):
        self.task.status = 'COMPLETED'
        self.task.completed_at = timezone.now()
        self.task.save()
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'PENDING', 'rollback_comment': 'Marked complete by mistake'},
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'PENDING')
        self.assertIsNone(self.task.completed_at)
        self.assertTrue(
            ActivityLog.objects.filter(
                task=self.task,
                user=self.member,
                action='TASK_UPDATED',
                description__icontains='Reason: Marked complete by mistake',
            ).exists()
        )

    def test_leader_can_delete_task(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(reverse('core:task_delete', args=[self.task.id]))
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertFalse(Task.objects.filter(id=self.task.id).exists())

    def test_non_leader_cannot_delete_task(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(reverse('core:task_delete', args=[self.task.id]))
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.assertTrue(Task.objects.filter(id=self.task.id).exists())

    def test_leader_can_remove_member(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(
            reverse('core:remove_group_member', args=[self.group.id, self.member_two.id])
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertFalse(self.group.members.filter(id=self.member_two.id).exists())
        self.assertTrue(
            ActivityLog.objects.filter(
                user=self.owner,
                group=self.group,
                action='MEMBER_REMOVED',
            ).exists()
        )

    def test_non_leader_cannot_remove_member(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(
            reverse('core:remove_group_member', args=[self.group.id, self.member_two.id])
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertTrue(self.group.members.filter(id=self.member_two.id).exists())

    def test_leader_can_delete_group(self):
        self.client.login(username='owner', password='pass12345')
        response = self.client.post(reverse('core:group_delete', args=[self.group.id]))
        self.assertRedirects(response, reverse('core:group_list'))
        self.assertFalse(Group.objects.filter(id=self.group.id).exists())

    def test_non_leader_cannot_delete_group(self):
        self.client.login(username='member', password='pass12345')
        response = self.client.post(reverse('core:group_delete', args=[self.group.id]))
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertTrue(Group.objects.filter(id=self.group.id).exists())

    def test_my_tasks_separates_pending_and_completed(self):
        Task.objects.create(
            title='Completed Task',
            description='Already done',
            group=self.group,
            assigned_to=self.member,
            created_by=self.owner,
            deadline=timezone.now() + timedelta(days=2),
            status='COMPLETED',
        )
        self.client.login(username='member', password='pass12345')
        response = self.client.get(reverse('core:my_tasks'))
        self.assertEqual(response.status_code, 200)
        pending_titles = {task.title for task in response.context['pending_tasks']}
        completed_titles = {task.title for task in response.context['completed_tasks']}
        self.assertIn('Initial Task', pending_titles)
        self.assertIn('Completed Task', completed_titles)

    def test_my_tasks_quick_actions_keep_existing_file_link(self):
        # update_task_status overwrites file_link with the posted value, so quick actions must resend it.
        self.task.file_link = 'https://drive.google.com/keep-me'
        self.task.save()
        self.client.login(username='member', password='pass12345')
        response = self.client.get(reverse('core:my_tasks'))
        self.assertContains(
            response,
            '<input type="hidden" name="file_link" value="https://drive.google.com/keep-me">',
            count=2,
            html=True,
        )

    def test_join_group_by_code_adds_member_and_logs_activity(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.post(
            reverse('core:join_group'),
            {'join_code': self.group.join_code.lower()},
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertTrue(self.group.members.filter(id=self.outsider.id).exists())
        self.assertTrue(
            ActivityLog.objects.filter(
                user=self.outsider,
                group=self.group,
                action='GROUP_JOINED',
            ).exists()
        )

    def test_join_group_with_invalid_code_does_not_add_member(self):
        self.client.login(username='outsider', password='pass12345')
        response = self.client.post(
            reverse('core:join_group'),
            {'join_code': 'INVALID1'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.group.members.filter(id=self.outsider.id).exists())
        # Error messages map to Bootstrap's "danger" style and render once (in the toast stack only).
        self.assertContains(response, 'class="flash flash-danger"', count=1)


class AccessControlEdgeCaseTests(TaskTrackTestCase):
    def test_all_views_redirect_anonymous_users_to_login(self):
        get_urls = [
            reverse('core:dashboard'),
            reverse('core:group_list'),
            reverse('core:group_create'),
            reverse('core:join_group'),
            reverse('core:group_detail', args=[self.group.id]),
            reverse('core:task_create', args=[self.group.id]),
            reverse('core:task_detail', args=[self.task.id]),
            reverse('core:task_edit', args=[self.task.id]),
            reverse('core:my_tasks'),
            reverse('core:activity_log'),
        ]
        post_urls = [
            reverse('core:update_task_status', args=[self.task.id]),
            reverse('core:task_delete', args=[self.task.id]),
            reverse('core:group_delete', args=[self.group.id]),
            reverse('core:remove_group_member', args=[self.group.id, self.member.id]),
        ]
        login_url = reverse('accounts:login')
        for url in get_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, f'{login_url}?next={url}', fetch_redirect_response=False)
        for url in post_urls:
            with self.subTest(url=url):
                response = self.client.post(url, {'status': 'COMPLETED'})
                self.assertRedirects(response, f'{login_url}?next={url}', fetch_redirect_response=False)
        self.assertTrue(Task.objects.filter(id=self.task.id, status='PENDING').exists())
        self.assertTrue(self.group.members.filter(id=self.member.id).exists())

    def test_post_only_endpoints_reject_get(self):
        self.client.force_login(self.owner)
        urls = [
            reverse('core:update_task_status', args=[self.task.id]),
            reverse('core:task_delete', args=[self.task.id]),
            reverse('core:group_delete', args=[self.group.id]),
            reverse('core:remove_group_member', args=[self.group.id, self.member.id]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(Task.objects.filter(id=self.task.id).exists())
        self.assertTrue(self.group.members.filter(id=self.member.id).exists())

    def test_unknown_ids_return_404(self):
        self.client.force_login(self.owner)
        urls = [
            reverse('core:group_detail', args=[99999]),
            reverse('core:task_create', args=[99999]),
            reverse('core:task_detail', args=[99999]),
            reverse('core:task_edit', args=[99999]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.post(reverse('core:remove_group_member', args=[self.group.id, 99999]))
        self.assertEqual(response.status_code, 404)

    def test_outsider_cannot_view_or_change_task(self):
        self.client.force_login(self.outsider)
        detail = self.client.get(reverse('core:task_detail', args=[self.task.id]))
        self.assertRedirects(detail, reverse('core:dashboard'))

        update = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'COMPLETED'},
        )
        self.assertRedirects(update, reverse('core:dashboard'))

        delete = self.client.post(reverse('core:task_delete', args=[self.task.id]))
        self.assertRedirects(delete, reverse('core:dashboard'))

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'PENDING')
        self.assertFalse(ActivityLog.objects.filter(user=self.outsider).exists())

    def test_outsider_cannot_manage_group(self):
        self.client.force_login(self.outsider)
        create_task = self.client.get(reverse('core:task_create', args=[self.group.id]))
        self.assertRedirects(create_task, reverse('core:group_list'))

        remove = self.client.post(
            reverse('core:remove_group_member', args=[self.group.id, self.member.id])
        )
        self.assertRedirects(remove, reverse('core:group_list'))

        delete = self.client.post(reverse('core:group_delete', args=[self.group.id]))
        self.assertRedirects(delete, reverse('core:group_list'))

        self.assertTrue(Group.objects.filter(id=self.group.id).exists())
        self.assertTrue(self.group.members.filter(id=self.member.id).exists())

    def test_leader_cannot_remove_themselves(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('core:remove_group_member', args=[self.group.id, self.owner.id])
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertTrue(self.group.members.filter(id=self.owner.id).exists())
        self.assertFalse(ActivityLog.objects.filter(action='MEMBER_REMOVED').exists())

    def test_removing_a_non_member_is_rejected_without_logging(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('core:remove_group_member', args=[self.group.id, self.outsider.id])
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertFalse(ActivityLog.objects.filter(action='MEMBER_REMOVED').exists())

    def test_removed_member_loses_access_even_to_their_assigned_task(self):
        self.group.members.remove(self.member)
        self.client.force_login(self.member)

        group_page = self.client.get(reverse('core:group_detail', args=[self.group.id]))
        self.assertRedirects(group_page, reverse('core:group_list'))

        task_page = self.client.get(reverse('core:task_detail', args=[self.task.id]))
        self.assertRedirects(task_page, reverse('core:dashboard'))

        update = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'COMPLETED'},
        )
        self.assertRedirects(update, reverse('core:dashboard'))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'PENDING')

    def test_assignee_who_is_not_leader_cannot_edit_or_delete_task(self):
        self.client.force_login(self.member)
        edit = self.client.post(
            reverse('core:task_edit', args=[self.task.id]),
            {
                'title': 'Hijacked',
                'description': '',
                'assigned_to': self.member.id,
                'deadline': form_deadline(self.task.deadline),
                'file_link': '',
            },
        )
        self.assertRedirects(edit, reverse('core:task_detail', args=[self.task.id]))
        delete = self.client.post(reverse('core:task_delete', args=[self.task.id]))
        self.assertRedirects(delete, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Initial Task')

    def test_task_detail_flags_reflect_role(self):
        cases = [
            (self.owner, True, True, True),
            (self.member, True, False, False),
            (self.member_two, False, False, False),
        ]
        for user, can_update, can_edit, can_delete in cases:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(reverse('core:task_detail', args=[self.task.id]))
                self.assertEqual(response.context['can_update_status'], can_update)
                self.assertEqual(response.context['can_edit_task'], can_edit)
                self.assertEqual(response.context['can_delete_task'], can_delete)

    def test_sidebar_lists_only_the_users_groups(self):
        other_group = Group.objects.create(name='Outsider Group', created_by=self.outsider)
        other_group.members.add(self.outsider)
        self.client.force_login(self.member)
        response = self.client.get(reverse('core:dashboard'))
        sidebar_ids = {group.id for group in response.context['sidebar_groups']}
        self.assertEqual(sidebar_ids, {self.group.id})
        self.assertNotContains(response, 'Outsider Group')


class TaskLifecycleEdgeCaseTests(TaskTrackTestCase):
    def task_form_data(self, **overrides):
        data = {
            'title': 'Edge Task',
            'description': '',
            'assigned_to': self.member.id,
            'deadline': form_deadline(timezone.now() + timedelta(days=3)),
            'file_link': '',
        }
        data.update(overrides)
        return data

    def test_task_create_rejects_invalid_input(self):
        self.client.force_login(self.owner)
        cases = {
            'assignee outside group': {'assigned_to': self.outsider.id},
            'past deadline': {'deadline': form_deadline(timezone.now() - timedelta(hours=1))},
            'invalid file link': {'file_link': 'not-a-url'},
            'missing title': {'title': ''},
        }
        for label, overrides in cases.items():
            with self.subTest(label):
                response = self.client.post(
                    reverse('core:task_create', args=[self.group.id]),
                    self.task_form_data(**overrides),
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
        self.assertEqual(self.group.tasks.count(), 1)
        self.assertFalse(ActivityLog.objects.filter(action='TASK_CREATED').exists())

    def test_task_create_form_only_offers_group_members(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('core:task_create', args=[self.group.id]))
        choices = set(response.context['form'].fields['assigned_to'].queryset)
        self.assertEqual(choices, {self.owner, self.member, self.member_two})

    def test_task_edit_rejects_assignee_outside_group(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('core:task_edit', args=[self.task.id]),
            self.task_form_data(assigned_to=self.outsider.id),
        )
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.assigned_to, self.member)
        self.assertFalse(ActivityLog.objects.filter(action='TASK_UPDATED').exists())

    def test_task_edit_without_changes_logs_no_field_changes(self):
        deadline = (timezone.now() + timedelta(days=2)).replace(second=0, microsecond=0)
        Task.objects.filter(id=self.task.id).update(deadline=deadline)
        self.task.refresh_from_db()
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('core:task_edit', args=[self.task.id]),
            self.task_form_data(
                title=self.task.title,
                description=self.task.description,
                deadline=form_deadline(deadline),
            ),
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        log = ActivityLog.objects.get(action='TASK_UPDATED', task=self.task)
        self.assertIn('no field changes', log.description)

    def test_update_status_rejects_unknown_or_overdue_values(self):
        self.client.force_login(self.member)
        for status in ['OVERDUE', 'DONE', '']:
            with self.subTest(status=status):
                response = self.client.post(
                    reverse('core:update_task_status', args=[self.task.id]),
                    {'status': status},
                )
                self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'PENDING')
        self.assertFalse(ActivityLog.objects.filter(action='TASK_UPDATED').exists())

    def test_completing_again_keeps_original_completed_at(self):
        original = timezone.now() - timedelta(days=1)
        Task.objects.filter(id=self.task.id).update(status='COMPLETED', completed_at=original)
        self.client.force_login(self.member)
        self.client.post(reverse('core:update_task_status', args=[self.task.id]), {'status': 'COMPLETED'})
        self.task.refresh_from_db()
        self.assertEqual(self.task.completed_at, original)

    def test_rollback_with_whitespace_only_comment_is_rejected(self):
        Task.objects.filter(id=self.task.id).update(status='COMPLETED', completed_at=timezone.now())
        self.client.force_login(self.member)
        self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'IN_PROGRESS', 'rollback_comment': '   '},
        )
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'COMPLETED')
        self.assertIsNotNone(self.task.completed_at)

    def test_rollback_to_in_progress_clears_completed_at(self):
        Task.objects.filter(id=self.task.id).update(status='COMPLETED', completed_at=timezone.now())
        self.client.force_login(self.owner)
        self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'IN_PROGRESS', 'rollback_comment': 'Needs another review'},
        )
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'IN_PROGRESS')
        self.assertIsNone(self.task.completed_at)

    def test_completing_an_overdue_task_marks_it_completed(self):
        self.make_overdue(self.task)
        self.client.force_login(self.member)
        self.client.post(reverse('core:update_task_status', args=[self.task.id]), {'status': 'COMPLETED'})
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'COMPLETED')
        self.assertIsNotNone(self.task.completed_at)
        self.assertFalse(self.task.is_overdue())

    def test_overdue_task_can_be_moved_to_in_progress(self):
        self.make_overdue(self.task)
        self.client.force_login(self.member)
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'IN_PROGRESS'},
            follow=True,
        )
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'IN_PROGRESS')
        self.assertTrue(self.task.is_overdue())
        self.assertContains(response, 'updated successfully')
        log = ActivityLog.objects.get(action='TASK_UPDATED', task=self.task)
        self.assertIn('from Overdue to In Progress', log.description)

    def test_overdue_task_set_to_pending_stays_overdue_and_says_so(self):
        self.make_overdue(self.task)
        self.client.force_login(self.member)
        response = self.client.post(
            reverse('core:update_task_status', args=[self.task.id]),
            {'status': 'PENDING'},
            follow=True,
        )
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'OVERDUE')
        self.assertContains(response, 'past its deadline')
        self.assertNotContains(response, 'updated successfully')
        log = ActivityLog.objects.get(action='TASK_UPDATED', task=self.task)
        self.assertIn('from Overdue to Overdue', log.description)

    def test_late_in_progress_task_keeps_its_status_on_save(self):
        Task.objects.filter(id=self.task.id).update(
            status='IN_PROGRESS', deadline=timezone.now() - timedelta(days=1)
        )
        self.task.refresh_from_db()
        self.task.description = 'touched'
        self.task.save()
        self.assertEqual(self.task.status, 'IN_PROGRESS')
        self.assertTrue(self.task.is_overdue())

    def test_leader_can_edit_overdue_task_without_changing_deadline(self):
        self.make_overdue(self.task)
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('core:task_edit', args=[self.task.id]),
            self.task_form_data(title='Renamed late task', deadline=form_deadline(self.task.deadline)),
        )
        self.assertRedirects(response, reverse('core:task_detail', args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'Renamed late task')
        self.assertEqual(self.task.status, 'OVERDUE')
        log = ActivityLog.objects.get(action='TASK_UPDATED', task=self.task)
        self.assertNotIn('deadline', log.description)

    def test_editing_overdue_task_cannot_pick_a_different_past_deadline(self):
        self.make_overdue(self.task)
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('core:task_edit', args=[self.task.id]),
            self.task_form_data(deadline=form_deadline(self.task.deadline - timedelta(days=1))),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('deadline', response.context['form'].errors)

    def test_extending_overdue_deadline_returns_task_to_pending(self):
        self.make_overdue(self.task)
        self.client.force_login(self.owner)
        self.client.post(
            reverse('core:task_edit', args=[self.task.id]),
            self.task_form_data(
                title=self.task.title,
                deadline=form_deadline(timezone.now() + timedelta(days=2)),
            ),
        )
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'PENDING')
        self.assertFalse(self.task.is_overdue())

    def test_task_save_marks_past_deadline_overdue_unless_completed(self):
        past = timezone.now() - timedelta(hours=1)
        pending = Task(
            title='Late', group=self.group, assigned_to=self.member,
            created_by=self.owner, deadline=past, status='PENDING',
        )
        pending.save()
        self.assertEqual(pending.status, 'OVERDUE')
        self.assertTrue(pending.is_overdue())

        done = Task(
            title='Late but done', group=self.group, assigned_to=self.member,
            created_by=self.owner, deadline=past, status='COMPLETED',
        )
        done.save()
        self.assertEqual(done.status, 'COMPLETED')
        self.assertFalse(done.is_overdue())

    def test_deleting_task_logs_activity_without_task_link(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('core:task_delete', args=[self.task.id]))
        log = ActivityLog.objects.get(action='TASK_DELETED')
        self.assertIsNone(log.task)
        self.assertEqual(log.group, self.group)
        self.assertIn('Initial Task', log.description)

    def test_deleting_group_removes_its_tasks_and_activity(self):
        ActivityLog.objects.create(user=self.owner, group=self.group, action='GROUP_CREATED', description='x')
        self.client.force_login(self.owner)
        self.client.post(reverse('core:group_delete', args=[self.group.id]))
        self.assertFalse(Task.objects.filter(id=self.task.id).exists())
        self.assertFalse(ActivityLog.objects.filter(group_id=self.group.id).exists())


class GroupMembershipEdgeCaseTests(TaskTrackTestCase):
    def test_group_create_makes_creator_leader_member_and_logs(self):
        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse('core:group_create'),
            {'name': 'Beta Team', 'description': ''},
        )
        group = Group.objects.get(name='Beta Team')
        self.assertRedirects(response, reverse('core:group_detail', args=[group.id]))
        self.assertEqual(group.created_by, self.outsider)
        self.assertTrue(group.members.filter(id=self.outsider.id).exists())
        self.assertEqual(len(group.join_code), 8)
        self.assertTrue(ActivityLog.objects.filter(group=group, action='GROUP_CREATED').exists())

    def test_group_create_requires_a_name(self):
        self.client.force_login(self.outsider)
        response = self.client.post(reverse('core:group_create'), {'name': '', 'description': ''})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Group.objects.filter(created_by=self.outsider).exists())

    def test_join_code_collision_is_regenerated(self):
        clash = Group.objects.create(name='Clash', created_by=self.owner, join_code=self.group.join_code)
        self.assertNotEqual(clash.join_code, self.group.join_code)
        self.assertEqual(len(clash.join_code), 8)

    def test_join_code_is_stable_across_saves(self):
        code = self.group.join_code
        self.group.name = 'Renamed'
        self.group.save()
        self.group.refresh_from_db()
        self.assertEqual(self.group.join_code, code)

    def test_joining_with_padded_lowercase_code_works(self):
        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse('core:join_group'),
            {'join_code': f'  {self.group.join_code.lower()}  '},
        )
        self.assertRedirects(response, reverse('core:group_detail', args=[self.group.id]))
        self.assertTrue(self.group.members.filter(id=self.outsider.id).exists())

    def test_joining_a_group_twice_does_not_duplicate_membership_or_log(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse('core:join_group'), {'join_code': self.group.join_code})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.group.members.filter(id=self.member.id).count(), 1)
        self.assertFalse(ActivityLog.objects.filter(action='GROUP_JOINED').exists())
        self.assertContains(response, 'already a member')

    def test_join_code_with_wrong_length_is_rejected(self):
        self.client.force_login(self.outsider)
        for code in ['ABC', 'ABCDEFGHI']:
            with self.subTest(code=code):
                response = self.client.post(reverse('core:join_group'), {'join_code': code})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'valid 8-character join code')
        self.assertFalse(self.group.members.filter(id=self.outsider.id).exists())

    def test_rejoining_after_removal_restores_access(self):
        self.group.members.remove(self.member_two)
        self.client.force_login(self.member_two)
        self.client.post(reverse('core:join_group'), {'join_code': self.group.join_code})
        response = self.client.get(reverse('core:group_detail', args=[self.group.id]))
        self.assertEqual(response.status_code, 200)


class StatsAndContributionEdgeCaseTests(TaskTrackTestCase):
    def contributions(self, group=None, user=None):
        self.client.force_login(user or self.owner)
        response = self.client.get(reverse('core:group_detail', args=[(group or self.group).id]))
        rows = {row['user'].username: row for row in response.context['member_contributions']}
        return response, rows

    def test_empty_group_has_zero_stats_without_errors(self):
        empty = Group.objects.create(name='Empty', created_by=self.owner)
        empty.members.add(self.owner, self.member)
        response, rows = self.contributions(group=empty)
        self.assertEqual(response.context['completion_percentage'], 0)
        self.assertEqual(response.context['total_group_activities'], 0)
        for row in rows.values():
            self.assertEqual(
                (row['assigned'], row['completion_rate'], row['contribution_share'], row['activity_share']),
                (0, 0, 0, 0),
            )

    def test_contributions_ignore_other_groups(self):
        other = Group.objects.create(name='Other', created_by=self.member)
        other.members.add(self.member)
        self.make_task('Elsewhere', group=other, status='COMPLETED', completed_at=timezone.now())
        ActivityLog.objects.create(user=self.member, group=other, action='TASK_UPDATED', description='x')

        _, rows = self.contributions()
        self.assertEqual(rows['member']['assigned'], 1)
        self.assertEqual(rows['member']['completed'], 0)
        self.assertEqual(rows['member']['activity_count'], 0)

    def test_overdue_tasks_count_as_assigned_but_not_completed(self):
        self.make_overdue(self.task)
        self.make_task('Finished', status='COMPLETED', completed_at=timezone.now())
        response, rows = self.contributions()
        self.assertEqual(rows['member']['assigned'], 2)
        self.assertEqual(rows['member']['completed'], 1)
        self.assertAlmostEqual(rows['member']['completion_rate'], 50.0)
        self.assertEqual(response.context['completion_percentage'], 50)

    def test_shares_across_members_add_up_to_100(self):
        self.make_task('A', assigned_to=self.member, status='COMPLETED', completed_at=timezone.now())
        self.make_task('B', assigned_to=self.member_two, status='COMPLETED', completed_at=timezone.now())
        self.make_task('C', assigned_to=self.member_two, status='COMPLETED', completed_at=timezone.now())
        for user in [self.owner, self.member, self.member_two, self.member_two]:
            ActivityLog.objects.create(user=user, group=self.group, action='TASK_UPDATED', description='x')

        _, rows = self.contributions()
        self.assertAlmostEqual(sum(row['contribution_share'] for row in rows.values()), 100.0)
        self.assertAlmostEqual(sum(row['activity_share'] for row in rows.values()), 100.0)
        self.assertAlmostEqual(rows['member_two']['contribution_share'], 200 / 3)

    def test_removed_member_drops_out_of_contribution_table(self):
        self.group.members.remove(self.member_two)
        _, rows = self.contributions()
        self.assertNotIn('member_two', rows)

    def test_dashboard_with_no_tasks_has_zero_rate(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.context['total_assigned'], 0)
        self.assertEqual(response.context['completion_rate'], 0)
        self.assertEqual(response.context['groups_count'], 0)

    def test_dashboard_completion_rate_rounds_to_one_decimal(self):
        self.make_task('Two')
        self.make_task('Three', status='COMPLETED', completed_at=timezone.now())
        self.client.force_login(self.member)
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.context['completion_rate'], 33.3)

    def test_dashboard_lists_at_most_ten_open_tasks(self):
        for i in range(11):
            self.make_task(f'Open {i}')
        self.make_task('Done', status='COMPLETED', completed_at=timezone.now())
        self.client.force_login(self.member)
        response = self.client.get(reverse('core:dashboard'))
        open_tasks = list(response.context['assigned_tasks'])
        self.assertEqual(len(open_tasks), 10)
        self.assertTrue(all(task.status != 'COMPLETED' for task in open_tasks))

    def test_activity_views_show_only_own_entries_and_cap_at_50(self):
        ActivityLog.objects.bulk_create(
            [ActivityLog(user=self.member, group=self.group, action='TASK_UPDATED', description=f'm{i}') for i in range(55)]
            + [ActivityLog(user=self.owner, group=self.group, action='TASK_UPDATED', description='owner entry')]
        )
        self.client.force_login(self.member)
        log_page = self.client.get(reverse('core:activity_log'))
        self.assertEqual(len(log_page.context['activities']), 50)
        self.assertTrue(all(a.user_id == self.member.id for a in log_page.context['activities']))

        dashboard = self.client.get(reverse('core:dashboard'))
        self.assertEqual(len(dashboard.context['recent_activities']), 10)
        self.assertNotContains(dashboard, 'owner entry')

    def test_removed_members_old_tasks_leave_their_dashboard_and_my_tasks(self):
        self.make_task('Finished before removal', status='COMPLETED', completed_at=timezone.now())
        self.group.members.remove(self.member)
        self.client.force_login(self.member)

        dashboard = self.client.get(reverse('core:dashboard'))
        self.assertEqual(list(dashboard.context['assigned_tasks']), [])
        self.assertEqual(dashboard.context['total_assigned'], 0)
        self.assertEqual(dashboard.context['completion_rate'], 0)

        my_tasks = self.client.get(reverse('core:my_tasks'))
        self.assertEqual(list(my_tasks.context['pending_tasks']), [])
        self.assertEqual(list(my_tasks.context['completed_tasks']), [])

    def test_removing_member_mentions_their_open_tasks(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse('core:remove_group_member', args=[self.group.id, self.member.id]),
            follow=True,
        )
        self.assertContains(response, '1 open task still assigned to them should be reassigned.')

    def test_my_tasks_excludes_tasks_assigned_to_others(self):
        self.make_task('Not mine', assigned_to=self.member_two)
        self.client.force_login(self.member)
        response = self.client.get(reverse('core:my_tasks'))
        titles = {task.title for task in response.context['pending_tasks']}
        self.assertEqual(titles, {'Initial Task'})


class TaskCommentTests(TaskTrackTestCase):
    def comment_url(self, task=None):
        return reverse('core:task_comment_create', args=[(task or self.task).id])

    def delete_url(self, comment):
        return reverse('core:task_comment_delete', args=[comment.id])

    def detail_url(self, task=None):
        return reverse('core:task_detail', args=[(task or self.task).id])

    def add_comment(self, author, body='Looks good', task=None):
        return TaskComment.objects.create(task=task or self.task, author=author, body=body)

    def messages_of(self, response):
        return [str(message) for message in response.context['messages']]

    def test_assignee_and_non_assignee_members_can_comment(self):
        for user in (self.member, self.member_two, self.owner):
            self.client.force_login(user)
            response = self.client.post(self.comment_url(), {'body': f'Note from {user.username}'})
            self.assertRedirects(response, f'{self.detail_url()}#comments', fetch_redirect_response=False)
        self.assertEqual(
            list(self.task.comments.values_list('author__username', flat=True)),
            ['member', 'member_two', 'owner'],
        )

    def test_comment_creates_activity_log_entry(self):
        self.client.force_login(self.member_two)
        self.client.post(self.comment_url(), {'body': 'Can I help with this?'})
        log = ActivityLog.objects.get(action='COMMENT_ADDED')
        self.assertEqual(log.user, self.member_two)
        self.assertEqual(log.group, self.group)
        self.assertEqual(log.task, self.task)

    def test_comment_counts_toward_activity_share(self):
        self.client.force_login(self.member_two)
        self.client.post(self.comment_url(), {'body': 'Progress update'})
        response = self.client.get(reverse('core:group_detail', args=[self.group.id]))
        rows = {row['user'].username: row for row in response.context['member_contributions']}
        self.assertEqual(rows['member_two']['activity_count'], 1)

    def test_comment_body_is_stripped_and_line_breaks_kept(self):
        self.client.force_login(self.member)
        self.client.post(self.comment_url(), {'body': '  first line\nsecond line  '})
        comment = self.task.comments.get()
        self.assertEqual(comment.body, 'first line\nsecond line')
        response = self.client.get(self.detail_url())
        self.assertContains(response, '<div class="comment-body">first line\nsecond line</div>', html=False)

    def test_comment_body_is_escaped(self):
        self.add_comment(self.member, body='<script>alert(1)</script>')
        self.client.force_login(self.member)
        response = self.client.get(self.detail_url())
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_blank_and_whitespace_comments_are_rejected(self):
        self.client.force_login(self.member)
        for body in ('', '   ', '\n\t \n'):
            response = self.client.post(self.comment_url(), {'body': body}, follow=True)
            self.assertRedirects(response, self.detail_url())
            self.assertIn('Comment cannot be empty.', self.messages_of(response))
        self.assertFalse(TaskComment.objects.exists())
        self.assertFalse(ActivityLog.objects.filter(action='COMMENT_ADDED').exists())

    def test_overlong_comment_is_rejected(self):
        self.client.force_login(self.member)
        self.client.post(self.comment_url(), {'body': 'x' * (TaskComment.BODY_MAX_LENGTH + 1)})
        self.assertFalse(TaskComment.objects.exists())
        self.client.post(self.comment_url(), {'body': 'x' * TaskComment.BODY_MAX_LENGTH})
        self.assertEqual(TaskComment.objects.count(), 1)

    def test_outsider_cannot_post_comment(self):
        self.client.force_login(self.outsider)
        response = self.client.post(self.comment_url(), {'body': 'Hi'}, follow=True)
        self.assertRedirects(response, reverse('core:dashboard'))
        self.assertIn('You do not have access to this task.', self.messages_of(response))
        self.assertFalse(TaskComment.objects.exists())

    def test_outsider_cannot_view_comments(self):
        self.add_comment(self.member, body='Secret plan')
        self.client.force_login(self.outsider)
        self.assertRedirects(self.client.get(self.detail_url()), reverse('core:dashboard'))

    def test_removed_member_cannot_view_or_post(self):
        self.add_comment(self.member_two, body='Before removal')
        self.group.members.remove(self.member_two)
        self.client.force_login(self.member_two)
        self.assertRedirects(self.client.get(self.detail_url()), reverse('core:dashboard'))
        response = self.client.post(self.comment_url(), {'body': 'After removal'})
        self.assertRedirects(response, reverse('core:dashboard'))
        self.assertEqual(TaskComment.objects.count(), 1)

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.post(self.comment_url(), {'body': 'Hi'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)
        comment = self.add_comment(self.member)
        response = self.client.post(self.delete_url(comment))
        self.assertIn('/accounts/login/', response.url)
        self.assertEqual(TaskComment.objects.count(), 1)

    def test_comment_endpoints_reject_get(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.comment_url()).status_code, 405)
        comment = self.add_comment(self.member)
        self.assertEqual(self.client.get(self.delete_url(comment)).status_code, 405)

    def test_comment_endpoints_404_for_missing_objects(self):
        self.client.force_login(self.member)
        self.assertEqual(
            self.client.post(reverse('core:task_comment_create', args=[99999]), {'body': 'Hi'}).status_code, 404
        )
        self.assertEqual(self.client.post(reverse('core:task_comment_delete', args=[99999])).status_code, 404)

    def test_task_detail_lists_comments_oldest_first_with_empty_state(self):
        self.client.force_login(self.member_two)
        self.assertContains(self.client.get(self.detail_url()), 'No comments yet')
        first = self.add_comment(self.owner, body='First')
        second = self.add_comment(self.member, body='Second')
        response = self.client.get(self.detail_url())
        self.assertEqual(list(response.context['comments']), [first, second])
        self.assertNotContains(response, 'No comments yet')

    def test_author_can_delete_own_comment(self):
        comment = self.add_comment(self.member_two)
        self.client.force_login(self.member_two)
        response = self.client.post(self.delete_url(comment))
        self.assertRedirects(response, f'{self.detail_url()}#comments', fetch_redirect_response=False)
        self.assertFalse(TaskComment.objects.exists())
        log = ActivityLog.objects.get(action='COMMENT_DELETED')
        self.assertEqual(log.user, self.member_two)
        self.assertIn('deleted their comment', log.description)

    def test_leader_can_delete_any_comment(self):
        comment = self.add_comment(self.member)
        self.client.force_login(self.owner)
        self.client.post(self.delete_url(comment))
        self.assertFalse(TaskComment.objects.exists())
        self.assertIn("deleted member's comment", ActivityLog.objects.get(action='COMMENT_DELETED').description)

    def test_other_member_cannot_delete_comment(self):
        comment = self.add_comment(self.member)
        self.client.force_login(self.member_two)
        response = self.client.post(self.delete_url(comment), follow=True)
        self.assertRedirects(response, self.detail_url())
        self.assertIn(
            'Only the comment author or the group leader can delete this comment.',
            self.messages_of(response),
        )
        self.assertEqual(TaskComment.objects.count(), 1)

    def test_outsider_and_removed_author_cannot_delete(self):
        comment = self.add_comment(self.member_two)
        self.client.force_login(self.outsider)
        self.assertRedirects(self.client.post(self.delete_url(comment)), reverse('core:dashboard'))
        self.group.members.remove(self.member_two)
        self.client.force_login(self.member_two)
        self.assertRedirects(self.client.post(self.delete_url(comment)), reverse('core:dashboard'))
        self.assertEqual(TaskComment.objects.count(), 1)

    def test_delete_button_shown_only_to_author_and_leader(self):
        self.add_comment(self.member)
        delete_label = 'aria-label="Delete comment by member"'
        for user, visible in ((self.member, True), (self.owner, True), (self.member_two, False)):
            self.client.force_login(user)
            response = self.client.get(self.detail_url())
            if visible:
                self.assertContains(response, delete_label)
            else:
                self.assertNotContains(response, delete_label)

    def test_deleting_task_removes_its_comments(self):
        self.add_comment(self.member)
        self.task.delete()
        self.assertFalse(TaskComment.objects.exists())

    def test_group_detail_shows_comment_counts_without_extra_queries(self):
        other = self.make_task('Second task')
        self.add_comment(self.member)
        self.add_comment(self.owner)
        self.add_comment(self.member_two, task=other)
        self.client.force_login(self.member)
        url = reverse('core:group_detail', args=[self.group.id])
        response = self.client.get(url)
        counts = {task.title: task.comment_count for task in response.context['tasks']}
        self.assertEqual(counts, {'Initial Task': 2, 'Second task': 1})

        with CaptureQueriesContext(connection) as before:
            self.client.get(url)
        for index in range(3):
            self.add_comment(self.member, task=self.make_task(f'Extra {index}'))
        with CaptureQueriesContext(connection) as after:
            self.client.get(url)
        self.assertEqual(len(after.captured_queries), len(before.captured_queries))

    def test_task_detail_comment_queries_do_not_grow_with_comments(self):
        self.client.force_login(self.member)
        self.add_comment(self.member)
        with CaptureQueriesContext(connection) as before:
            self.client.get(self.detail_url())
        for user in (self.owner, self.member_two, self.member):
            self.add_comment(user)
        with CaptureQueriesContext(connection) as after:
            self.client.get(self.detail_url())
        self.assertEqual(len(after.captured_queries), len(before.captured_queries))
