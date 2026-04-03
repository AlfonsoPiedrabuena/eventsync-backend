"""
Analytics services for E6 — aggregation queries over existing data.
No new models needed; all data comes from events, registrations, and email_logs.
"""
from django.db.models import Count, Q
from django.db.models.functions import TruncDay
from django.utils import timezone

from apps.events.models import Event
from apps.registrations.models import Registration


def get_event_summary(event: Event) -> dict:
    """
    Returns aggregated metrics for a single event.
    Used by the event analytics page.
    """
    qs = Registration.objects.filter(event=event)

    confirmed  = qs.filter(status=Registration.Status.CONFIRMED).count()
    waitlisted = qs.filter(status=Registration.Status.WAITLISTED).count()
    cancelled  = qs.filter(status=Registration.Status.CANCELLED).count()
    checked_in = qs.filter(checked_in=True).count()
    no_show    = confirmed - checked_in  # confirmed but didn't check in

    check_in_rate = round((checked_in / confirmed * 100), 1) if confirmed > 0 else 0.0

    capacity_utilization = None
    if event.max_capacity:
        capacity_utilization = round((confirmed / event.max_capacity * 100), 1)

    # Email stats (if communications app is available)
    emails_sent = emails_failed = 0
    try:
        from apps.communications.models import EmailLog
        email_qs = EmailLog.objects.filter(event=event)
        emails_sent   = email_qs.filter(status=EmailLog.Status.SENT).count()
        emails_failed = email_qs.filter(status=EmailLog.Status.FAILED).count()
    except Exception:
        pass

    return {
        'event_id':             str(event.id),
        'event_title':          event.title,
        'status':               event.status,
        'confirmed':            confirmed,
        'waitlisted':           waitlisted,
        'cancelled':            cancelled,
        'checked_in':           checked_in,
        'no_show':              max(no_show, 0),
        'check_in_rate':        check_in_rate,
        'max_capacity':         event.max_capacity,
        'capacity_utilization': capacity_utilization,
        'emails_sent':          emails_sent,
        'emails_failed':        emails_failed,
    }


def get_registrations_timeline(event: Event) -> dict:
    """
    Returns daily registration counts since the event was created.
    Used to draw the registrations-over-time chart.
    """
    daily = (
        Registration.objects
        .filter(event=event, status__in=[
            Registration.Status.CONFIRMED,
            Registration.Status.WAITLISTED,
        ])
        .annotate(day=TruncDay('created_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    labels     = []
    daily_vals = []
    cumulative = []
    running    = 0

    for row in daily:
        labels.append(row['day'].strftime('%Y-%m-%d'))
        daily_vals.append(row['count'])
        running += row['count']
        cumulative.append(running)

    return {
        'labels':     labels,
        'daily':      daily_vals,
        'cumulative': cumulative,
    }


def get_tenant_dashboard() -> dict:
    """
    Returns global metrics for the current tenant.
    Used by the main dashboard page.
    """
    all_events = Event.objects.all()

    events_by_status = dict(
        all_events
        .values('status')
        .annotate(n=Count('id'))
        .values_list('status', 'n')
    )

    total_registrations = Registration.objects.filter(
        status=Registration.Status.CONFIRMED
    ).count()

    total_checked_in = Registration.objects.filter(checked_in=True).count()

    now = timezone.now()
    upcoming = (
        all_events
        .filter(status=Event.Status.PUBLISHED, start_date__gte=now)
        .annotate(confirmed=Count(
            'registrations',
            filter=Q(registrations__status=Registration.Status.CONFIRMED)
        ))
        .order_by('start_date')
        .values('id', 'title', 'start_date', 'confirmed', 'max_capacity')[:5]
    )

    # Top 5 events by confirmed registrations
    top_events = (
        all_events
        .annotate(confirmed=Count(
            'registrations',
            filter=Q(registrations__status=Registration.Status.CONFIRMED)
        ))
        .order_by('-confirmed')
        .values('id', 'title', 'status', 'confirmed')[:5]
    )

    return {
        'total_events':       all_events.count(),
        'events_by_status':   events_by_status,
        'total_registrations': total_registrations,
        'total_checked_in':   total_checked_in,
        'upcoming_events':    list(upcoming),
        'top_events':         list(top_events),
    }
