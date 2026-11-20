from .models import Group


def sidebar_groups(request):
    if not request.user.is_authenticated:
        return {}
    # Lazy queryset: only hits the database when a template renders the sidebar.
    return {'sidebar_groups': Group.objects.filter(members=request.user).only('id', 'name')}
