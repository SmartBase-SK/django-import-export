from __future__ import unicode_literals
import re

class BaseInstanceLoader(object):
    """
    Base abstract implementation of instance loader.
    """

    def __init__(self, resource, dataset=None):
        self.resource = resource
        self.dataset = dataset

    def get_instance(self, row):
        raise NotImplementedError


class ModelInstanceLoader(BaseInstanceLoader):
    """
    Instance loader for Django model.

    Lookup for model instance by ``import_id_fields``.
    """

    def get_queryset(self):
        return self.resource._meta.model.objects.all()

    def get_instance(self, row):
        try:
            params = {}
            for key in self.resource.get_import_id_fields():
                field = self.resource.fields[key]
                if not field.clean(row):
                    # if NO id is set
                    r = re.compile("slug_*")
                    for field_i in self.resource.get_fields():
                        if r.match(field_i.attribute):
                            return self.get_queryset().translated(slug=row[field_i.attribute]).first()
                else:
                    params[field.attribute] = field.clean(row)
            return self.get_queryset().get(**params)
        except self.resource._meta.model.DoesNotExist:
            return None


class CachedInstanceLoader(ModelInstanceLoader):
    """
    Loads all possible model instances in dataset avoid hitting database for
    every ``get_instance`` call.

    This instance loader work only when there is one ``import_id_fields``
    field.
    """

    def __init__(self, *args, **kwargs):
        super(CachedInstanceLoader, self).__init__(*args, **kwargs)

        pk_field_name = self.resource.get_import_id_fields()[0]
        self.pk_field = self.resource.fields[pk_field_name]

        ids = [self.pk_field.clean(row) for row in self.dataset.dict]
        qs = self.get_queryset().filter(**{
            "%s__in" % self.pk_field.attribute: ids
            })

        self.all_instances = dict([
            (self.pk_field.get_value(instance), instance)
            for instance in qs])

    def get_instance(self, row):
        return self.all_instances.get(self.pk_field.clean(row))
