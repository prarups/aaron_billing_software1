from django.core.management.base import BaseCommand
from core.models import ComboGroup
from django.db.models import Max
import re

class Command(BaseCommand):
    help = 'Populate missing combo_id values for existing ComboGroup records.'

    def handle(self, *args, **options):
        groups_without_id = ComboGroup.objects.filter(combo_id__isnull=True)
        if not groups_without_id.exists():
            self.stdout.write(self.style.SUCCESS('All ComboGroup records already have combo_id.'))
            return
        for group in groups_without_id:
            max_num = 0
            queryset = ComboGroup.objects.exclude(combo_id__isnull=True)
            if group.pk:
                queryset = queryset.exclude(pk=group.pk)
            for cb in queryset:
                match = re.search(r'\d+', cb.combo_id)
                if match:
                    num = int(match.group())
                    if num > max_num:
                        max_num = num
            if max_num == 0:
                max_id_qs = ComboGroup.objects.all()
                if group.pk:
                    max_id_qs = max_id_qs.exclude(pk=group.pk)
                max_id = max_id_qs.aggregate(max_id=Max('id'))['max_id'] or 0
                max_num = max_id
            next_num = max_num + 1
            candidate = f"CB-{next_num:04d}"
            while ComboGroup.objects.filter(combo_id=candidate).exists():
                next_num += 1
                candidate = f"CB-{next_num:04d}"
            group.combo_id = candidate
            group.save()
            self.stdout.write(self.style.SUCCESS(f'Set combo_id for {group.name} to {candidate}'))
        self.stdout.write(self.style.SUCCESS('Finished populating missing combo_id values.'))
