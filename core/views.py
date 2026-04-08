import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import GroupForm, JoinGroupForm, TaskForm
from .models import ActivityLog, Group, Task

logger = logging.getLogger('core')


def _is_group_member(user, group):
    return group.members.filter(id=user.id).exists()


def _is_group_leader(user, group):
    return group.created_by_id == user.id


@login_required
def dashboard(request):
    user = request.user
    user_groups = Group.objects.filter(members=user)

    assigned_tasks = Task.objects.filter(assigned_to=user).exclude(status='COMPLETED')[:10]
    completed_tasks = Task.objects.filter(assigned_to=user, status='COMPLETED')
    recent_activities = ActivityLog.objects.filter(user=user)[:10]

    total_assigned = Task.objects.filter(assigned_to=user).count()
    total_completed = completed_tasks.count()
    completion_rate = (total_completed / total_assigned * 100) if total_assigned > 0 else 0

    context = {
        'assigned_tasks': assigned_tasks,
        'completed_tasks': completed_tasks,
        'user_groups': user_groups,
        'groups_count': user_groups.count(),
        'recent_activities': recent_activities,
        'total_assigned': total_assigned,
        'total_completed': total_completed,
        'completion_rate': round(completion_rate, 1),
    }
    return render(request, 'core/dashboard.html', context)


@login_required
def group_list(request):
    groups = Group.objects.filter(members=request.user)
    return render(request, 'core/group_list.html', {'groups': groups})


@login_required
def group_create(request):
    if request.method == 'POST':
        form = GroupForm(request.POST)
        if form.is_valid():
            group = form.save(commit=False)
            group.created_by = request.user
            group.save()
            group.members.add(request.user)

            ActivityLog.objects.create(
                user=request.user,
                group=group,
                action='GROUP_CREATED',
                description=f'{request.user.username} created group: {group.name}',
            )
            logger.info(
                'event=group_created user_id=%s group_id=%s',
                request.user.id,
                group.id,
            )

            messages.success(request, f'Group "{group.name}" created successfully!')
            return redirect('core:group_detail', group_id=group.id)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = GroupForm()

    return render(request, 'core/group_form.html', {'form': form, 'title': 'Create Group'})


@login_required
def group_detail(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if not _is_group_member(request.user, group):
        messages.error(request, 'You are not a member of this group.')
        return redirect('core:group_list')

    tasks = group.tasks.all()
    total_tasks = tasks.count()
    completed_tasks = tasks.filter(status='COMPLETED').count()
    is_group_leader = _is_group_leader(request.user, group)

    member_contributions = []
    for member in group.members.all():
        assigned = Task.objects.filter(group=group, assigned_to=member).count()
        completed = Task.objects.filter(group=group, assigned_to=member, status='COMPLETED').count()
        member_contributions.append(
            {
                'user': member,
                'assigned': assigned,
                'completed': completed,
                'completion_rate': (completed / assigned * 100) if assigned > 0 else 0,
            }
        )

    context = {
        'group': group,
        'tasks': tasks,
        'member_contributions': member_contributions,
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'completion_percentage': (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
        'is_group_leader': is_group_leader,
    }
    return render(request, 'core/group_detail.html', context)


@login_required
def task_create(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if not _is_group_member(request.user, group):
        logger.warning(
            'event=task_create_denied reason=not_group_member user_id=%s group_id=%s',
            request.user.id,
            group.id,
        )
        messages.error(request, 'You are not a member of this group.')
        return redirect('core:group_list')

    if not _is_group_leader(request.user, group):
        logger.warning(
            'event=task_create_denied reason=not_group_leader user_id=%s group_id=%s',
            request.user.id,
            group.id,
        )
        messages.error(request, 'Only the group leader can create and assign tasks.')
        return redirect('core:group_detail', group_id=group.id)

    if request.method == 'POST':
        form = TaskForm(request.POST, group=group)
        if form.is_valid():
            task = form.save(commit=False)
            task.group = group
            task.created_by = request.user
            task.save()

            ActivityLog.objects.create(
                user=request.user,
                group=group,
                task=task,
                action='TASK_CREATED',
                description=(
                    f'{request.user.username} created task: {task.title} '
                    f'and assigned it to {task.assigned_to.username}'
                ),
            )
            logger.info(
                'event=task_created user_id=%s group_id=%s task_id=%s assigned_to_id=%s',
                request.user.id,
                group.id,
                task.id,
                task.assigned_to_id,
            )

            messages.success(request, f'Task "{task.title}" created successfully!')
            return redirect('core:group_detail', group_id=group.id)
    else:
        form = TaskForm(group=group)

    return render(
        request,
        'core/task_form.html',
        {
            'form': form,
            'group': group,
            'title': 'Create Task',
            'submit_label': 'Create Task',
        },
    )


@login_required
def task_detail(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    group = task.group

    if not _is_group_member(request.user, group):
        messages.error(request, 'You do not have access to this task.')
        return redirect('core:dashboard')

    can_update_status = _is_group_leader(request.user, group) or task.assigned_to_id == request.user.id
    can_delete_task = _is_group_leader(request.user, group)
    can_edit_task = _is_group_leader(request.user, group)

    context = {
        'task': task,
        'task_activities': task.activities.all()[:20],
        'can_update_status': can_update_status,
        'can_delete_task': can_delete_task,
        'can_edit_task': can_edit_task,
    }
    return render(request, 'core/task_detail.html', context)


@login_required
def task_edit(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    group = task.group

    if not _is_group_member(request.user, group):
        logger.warning(
            'event=task_edit_denied reason=not_group_member user_id=%s group_id=%s task_id=%s',
            request.user.id,
            group.id,
            task.id,
        )
        messages.error(request, 'You do not have access to this task.')
        return redirect('core:dashboard')

    if not _is_group_leader(request.user, group):
        logger.warning(
            'event=task_edit_denied reason=not_group_leader user_id=%s group_id=%s task_id=%s',
            request.user.id,
            group.id,
            task.id,
        )
        messages.error(request, 'Only the group leader can edit tasks.')
        return redirect('core:task_detail', task_id=task.id)

    if request.method == 'POST':
        old_values = {
            'title': task.title,
            'description': task.description,
            'assigned_to': task.assigned_to.username,
            'deadline': task.deadline,
            'file_link': task.file_link,
        }
        form = TaskForm(request.POST, instance=task, group=group)
        if form.is_valid():
            task = form.save()

            change_messages = []
            if old_values['title'] != task.title:
                change_messages.append(f'title from "{old_values["title"]}" to "{task.title}"')
            if old_values['description'] != task.description:
                change_messages.append('description')
            if old_values['assigned_to'] != task.assigned_to.username:
                change_messages.append(
                    f'assignee from "{old_values["assigned_to"]}" to "{task.assigned_to.username}"'
                )
            if old_values['deadline'] != task.deadline:
                change_messages.append(
                    f'deadline from {old_values["deadline"].strftime("%Y-%m-%d %H:%M")} '
                    f'to {task.deadline.strftime("%Y-%m-%d %H:%M")}'
                )
            if old_values['file_link'] != task.file_link:
                change_messages.append('file link')

            if not change_messages:
                change_summary = 'no field changes'
            else:
                change_summary = '; '.join(change_messages)

            ActivityLog.objects.create(
                user=request.user,
                group=group,
                task=task,
                action='TASK_UPDATED',
                description=f'{request.user.username} edited task "{task.title}": {change_summary}.',
            )
            logger.info(
                'event=task_edited user_id=%s group_id=%s task_id=%s changes="%s"',
                request.user.id,
                group.id,
                task.id,
                change_summary,
            )

            messages.success(request, f'Task "{task.title}" updated successfully.')
            return redirect('core:task_detail', task_id=task.id)
        messages.error(request, 'Please correct the errors below.')
    else:
        form = TaskForm(instance=task, group=group)

    context = {
        'form': form,
        'group': group,
        'title': 'Edit Task',
        'submit_label': 'Save Changes',
    }
    return render(request, 'core/task_form.html', context)


@login_required
@require_POST
def update_task_status(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    group = task.group

    if not _is_group_member(request.user, group):
        logger.warning(
            'event=task_status_update_denied reason=not_group_member user_id=%s group_id=%s task_id=%s',
            request.user.id,
            group.id,
            task.id,
        )
        messages.error(request, 'You do not have permission to update this task.')
        return redirect('core:dashboard')

    if not (_is_group_leader(request.user, group) or task.assigned_to_id == request.user.id):
        logger.warning(
            'event=task_status_update_denied reason=insufficient_permissions user_id=%s group_id=%s task_id=%s',
            request.user.id,
            group.id,
            task.id,
        )
        messages.error(request, 'Only the group leader or assigned member can update this task status.')
        return redirect('core:task_detail', task_id=task.id)

    new_status = request.POST.get('status')
    new_file_link = (request.POST.get('file_link') or '').strip()
    rollback_comment = (request.POST.get('rollback_comment') or '').strip()
    valid_statuses = ['PENDING', 'IN_PROGRESS', 'COMPLETED']

    if new_status not in valid_statuses:
        messages.error(request, 'Invalid status value.')
        return redirect('core:task_detail', task_id=task.id)

    old_status = task.status
    if old_status == 'COMPLETED' and new_status in ['PENDING', 'IN_PROGRESS'] and not rollback_comment:
        messages.error(request, 'A comment is required when moving a completed task back.')
        return redirect('core:task_detail', task_id=task.id)

    task.status = new_status
    task.file_link = new_file_link

    if new_status == 'COMPLETED' and old_status != 'COMPLETED':
        task.completed_at = timezone.now()
    elif old_status == 'COMPLETED' and new_status in ['PENDING', 'IN_PROGRESS']:
        task.completed_at = None

    task.save()

    status_map = dict(Task.STATUS_CHOICES)
    description = (
        f'{request.user.username} changed "{task.title}" from '
        f'{status_map.get(old_status, old_status)} to {status_map.get(new_status, new_status)}'
    )
    if rollback_comment:
        description += f'. Reason: {rollback_comment}'

    ActivityLog.objects.create(
        user=request.user,
        group=group,
        task=task,
        action='TASK_UPDATED',
        description=description,
    )
    logger.info(
        'event=task_status_updated user_id=%s group_id=%s task_id=%s old_status=%s new_status=%s',
        request.user.id,
        group.id,
        task.id,
        old_status,
        new_status,
    )
    messages.success(request, f'Task "{task.title}" updated successfully.')
    return redirect('core:task_detail', task_id=task.id)


@login_required
@require_POST
def task_delete(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    group = task.group

    if not _is_group_member(request.user, group):
        logger.warning(
            'event=task_delete_denied reason=not_group_member user_id=%s group_id=%s task_id=%s',
            request.user.id,
            group.id,
            task.id,
        )
        messages.error(request, 'You do not have permission to delete this task.')
        return redirect('core:dashboard')

    if not _is_group_leader(request.user, group):
        logger.warning(
            'event=task_delete_denied reason=not_group_leader user_id=%s group_id=%s task_id=%s',
            request.user.id,
            group.id,
            task.id,
        )
        messages.error(request, 'Only the group leader can delete tasks.')
        return redirect('core:task_detail', task_id=task.id)

    task_title = task.title
    task.delete()
    ActivityLog.objects.create(
        user=request.user,
        group=group,
        action='TASK_DELETED',
        description=f'{request.user.username} deleted task: {task_title}',
    )
    logger.info(
        'event=task_deleted user_id=%s group_id=%s task_title="%s"',
        request.user.id,
        group.id,
        task_title,
    )
    messages.success(request, f'Task "{task_title}" was deleted.')
    return redirect('core:group_detail', group_id=group.id)


@login_required
@require_POST
def group_delete(request, group_id):
    group = get_object_or_404(Group, id=group_id)

    if not _is_group_member(request.user, group):
        logger.warning(
            'event=group_delete_denied reason=not_group_member user_id=%s group_id=%s',
            request.user.id,
            group.id,
        )
        messages.error(request, 'You do not have permission to delete this group.')
        return redirect('core:group_list')

    if not _is_group_leader(request.user, group):
        logger.warning(
            'event=group_delete_denied reason=not_group_leader user_id=%s group_id=%s',
            request.user.id,
            group.id,
        )
        messages.error(request, 'Only the group leader can delete this group.')
        return redirect('core:group_detail', group_id=group.id)

    group_name = group.name
    group.delete()
    logger.info(
        'event=group_deleted user_id=%s group_name="%s"',
        request.user.id,
        group_name,
    )
    messages.success(request, f'Group "{group_name}" was deleted.')
    return redirect('core:group_list')


@login_required
@require_POST
def remove_group_member(request, group_id, user_id):
    group = get_object_or_404(Group, id=group_id)
    member = get_object_or_404(User, id=user_id)

    if not _is_group_member(request.user, group):
        logger.warning(
            'event=member_remove_denied reason=not_group_member user_id=%s group_id=%s target_user_id=%s',
            request.user.id,
            group.id,
            member.id,
        )
        messages.error(request, 'You do not have permission to manage this group.')
        return redirect('core:group_list')

    if not _is_group_leader(request.user, group):
        logger.warning(
            'event=member_remove_denied reason=not_group_leader user_id=%s group_id=%s target_user_id=%s',
            request.user.id,
            group.id,
            member.id,
        )
        messages.error(request, 'Only the group leader can remove members.')
        return redirect('core:group_detail', group_id=group.id)

    if member.id == group.created_by_id:
        messages.error(request, 'The group leader cannot be removed.')
        return redirect('core:group_detail', group_id=group.id)

    if not _is_group_member(member, group):
        messages.error(request, 'Selected user is not a member of this group.')
        return redirect('core:group_detail', group_id=group.id)

    group.members.remove(member)
    ActivityLog.objects.create(
        user=request.user,
        group=group,
        action='MEMBER_REMOVED',
        description=f'{request.user.username} removed {member.username} from the group.',
    )
    logger.info(
        'event=member_removed user_id=%s group_id=%s removed_user_id=%s',
        request.user.id,
        group.id,
        member.id,
    )
    messages.success(request, f'{member.username} was removed from the group.')
    return redirect('core:group_detail', group_id=group.id)


@login_required
def join_group(request):
    if request.method == 'POST':
        form = JoinGroupForm(request.POST)
        if form.is_valid():
            join_code = form.cleaned_data['join_code']
            try:
                group = Group.objects.get(join_code=join_code)
                if _is_group_member(request.user, group):
                    logger.info(
                        'event=group_join_noop_already_member user_id=%s group_id=%s',
                        request.user.id,
                        group.id,
                    )
                    messages.warning(request, 'You are already a member of this group.')
                else:
                    group.members.add(request.user)
                    ActivityLog.objects.create(
                        user=request.user,
                        group=group,
                        action='GROUP_JOINED',
                        description=f'{request.user.username} joined group: {group.name}',
                    )
                    logger.info(
                        'event=group_joined user_id=%s group_id=%s',
                        request.user.id,
                        group.id,
                    )
                    messages.success(request, f'You have joined "{group.name}"!')
                    return redirect('core:group_detail', group_id=group.id)
            except Group.DoesNotExist:
                logger.warning(
                    'event=group_join_failed reason=invalid_code user_id=%s join_code=%s',
                    request.user.id,
                    join_code,
                )
                messages.error(request, f'No group found with join code "{join_code}".')
        else:
            messages.error(request, 'Please enter a valid 8-character join code.')
    else:
        form = JoinGroupForm()

    return render(request, 'core/join_group.html', {'form': form})


@login_required
def my_tasks(request):
    pending_tasks = Task.objects.filter(assigned_to=request.user).exclude(status='COMPLETED')
    completed_tasks = Task.objects.filter(assigned_to=request.user, status='COMPLETED')

    context = {
        'pending_tasks': pending_tasks,
        'completed_tasks': completed_tasks,
    }
    return render(request, 'core/my_tasks.html', context)


@login_required
def activity_log(request):
    activities = ActivityLog.objects.filter(user=request.user)[:50]
    return render(request, 'core/activity_log.html', {'activities': activities})
