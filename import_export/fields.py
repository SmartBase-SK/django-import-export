from __future__ import unicode_literals

from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.db import DatabaseError
from django.utils import translation
from faker.providers import currency
from parler.utils.context import switch_language

from sbcore.loading import get_model
from . import widgets

from django.core.exceptions import ObjectDoesNotExist
from django.db.models.manager import Manager
from django.db.models.fields import NOT_PROVIDED

Product = get_model('catalog', 'Product')
""" :type:  core.catalog.models.Product"""
Price = get_model('pricing', 'Price')
""" :type:  core.pricing.models.Price"""
PriceLevel = get_model('pricing', 'PriceLevel')
""" :type:  core.pricing.models.PriceLevel"""
Currency = get_model('pricing', 'Currency')
""" :type:  core.pricing.models.Currency"""
TaxRatio = get_model('pricing', 'TaxRatio')
""" :type:  core.pricing.models.TaxRatio"""
AttributeOptionGroupValue = get_model('catalog', 'AttributeOptionGroupValue')
""" :type:  core.catalog.models.AttributeOptionGroupValue"""
AttributeOptionGroup = get_model('catalog', 'AttributeOptionGroup')
""" :type:  core.catalog.models.AttributeOptionGroup"""
AttributeOption = get_model('catalog', 'AttributeOption')
""" :type:  core.catalog.models.AttributeOption"""
CarouselImages = get_model('catalog', 'CarouselImages')
""" :type:  core.catalog.models.CarouselImages"""


class Field(object):
    """
    Field represent mapping between `object` field and representation of
    this field.

    :param attribute: A string of either an instance attribute or callable off
        the object.

    :param column_name: Lets you provide a name for the column that represents
        this field in the export.

    :param widget: Defines a widget that will be used to represent this
        field's data in the export.

    :param readonly: A Boolean which defines if this field will be ignored
        during import.

    :param default: This value will be returned by
        :meth:`~import_export.fields.Field.clean` if this field's widget did
        not return an adequate value.
    """
    empty_values = [None, '']

    def __init__(self, attribute=None, column_name=None, widget=None,
                 default=NOT_PROVIDED, readonly=False):
        self.attribute = attribute
        self.default = default
        self.column_name = column_name
        if not widget:
            widget = widgets.Widget()
        self.widget = widget
        self.readonly = readonly

    def __repr__(self):
        """
        Displays the module, class and name of the field.
        """
        path = '%s.%s' % (self.__class__.__module__, self.__class__.__name__)
        column_name = getattr(self, 'column_name', None)
        if column_name is not None:
            return '<%s: %s>' % (path, column_name)
        return '<%s>' % path

    def clean(self, data):
        """
        Translates the value stored in the imported datasource to an
        appropriate Python object and returns it.
        """
        try:
            value = data[self.column_name]
        except KeyError:
            raise KeyError("Column '%s' not found in dataset. Available "
                           "columns are: %s" % (self.column_name,
                                                list(data.keys())))

        try:
            value = self.widget.clean(value, row=data)
        except ValueError as e:
            raise ValueError("Column '%s': %s" % (self.column_name, e))

        if value in self.empty_values and self.default != NOT_PROVIDED:
            if callable(self.default):
                return self.default()
            return self.default

        return value

    def get_value(self, obj):
        """
        Returns the value of the object's attribute.
        """
        if self.attribute is None:
            return None

        attrs = self.attribute.split('__')
        value = obj

        for attr in attrs:
            try:
                value = getattr(value, attr, None)
            except (ValueError, ObjectDoesNotExist):
                # needs to have a primary key value before a many-to-many
                # relationship can be used.
                return None
            if value is None:
                return None

        # RelatedManager and ManyRelatedManager classes are callable in
        # Django >= 1.7 but we don't want to call them
        if callable(value) and not isinstance(value, Manager):
            value = value()
        return value

    def save(self, obj, data):
        """
        If this field is not declared readonly, the object's attribute will
        be set to the value returned by :meth:`~import_export.fields.Field.clean`.
        """
        if not self.readonly:
            attrs = self.attribute.split('__')
            for attr in attrs[:-1]:
                obj = getattr(obj, attr, None)
            # for ID field return, anyways the id will be lost!
            if attrs[-1] is 'id':
                return
            else:
                setattr(obj, attrs[-1], self.clean(data))

    def export(self, obj):
        """
        Returns value from the provided object converted to export
        representation.
        """
        value = self.get_value(obj)
        if value is None:
            return ""
        return self.widget.render(value, obj)


class TranslatableField(Field):
    def get_value(self, obj):

        if self.attribute is None:
            return None

        tmp = self.attribute.split('_')
        attr_name = "_".join(tmp[:-1])
        attr_language = tmp[-1]

        value = obj
        with switch_language(value, attr_language):
            translation.activate(attr_language)

            try:
                value = getattr(value, attr_name, None)
            except (ValueError, ObjectDoesNotExist):
                # needs to have a primary key value before a many-to-many
                # relationship can be used.
                return None
            if value is None:
                return None

            # RelatedManager and ManyRelatedManager classes are callable in
            # Django >= 1.7 but we don't want to call them
            if callable(value) and not isinstance(value, Manager):
                value = value()
            return value

    def save(self, obj, data):
        if not self.readonly:
            tmp = self.attribute.split('_')
            attr_name = "_".join(tmp[:-1])
            attr_language = tmp[-1]
            with switch_language(obj, attr_language):
                translation.activate(attr_language)
                field = obj._meta.model.translations.field.model._meta.get_field(attr_name)
                if field.blank and not field.null and not field.is_relation:
                    if self.clean(data) is None:
                        setattr(obj, attr_name, '')
                    else:
                        setattr(obj, attr_name, self.clean(data))
                else:
                    if attr_name == 'slug' and not obj.get_slug and Product.objects.translated(slug=self.clean(data)).exists():
                        raise ValueError(
                            'ERROR: in item: "{}" - Slug: "{}" ALREADY EXISTS. Slug has to be UNIQUE!'.format(obj.name,
                                                                                        self.clean(data)))
                    setattr(obj, attr_name, self.clean(data))


class PriceField(Field):
    def get_value(self, obj):

        if self.attribute is None:
            return None

        tmp = self.attribute.split('__')
        if 'price_lvl' in self.attribute:
            attr_currency = tmp[-1]
            attr_price_lvl_id = int(tmp[-4].partition('(')[-1].rpartition(')')[0])
            attr_tax_ratio = tmp[-5]
            try:
                price_obj = obj.prices.get(currency__code=attr_currency, tax_ratio__percentage=attr_tax_ratio, price_level_id=attr_price_lvl_id)
                value = price_obj._price_excluding_tax
                return value
            except (ValueError, ObjectDoesNotExist):
                return None
        else:
            attr_currency = tmp[-1]
            attr_tax_ratio = tmp[-2]

            try:
                price_obj = obj.prices.get(currency__code=attr_currency, tax_ratio__percentage=attr_tax_ratio, price_level=None)
                value = price_obj._price_excluding_tax
                return value
            except (ValueError, ObjectDoesNotExist):
                return None

    def save(self, obj, data):
        tmp = self.attribute.split('__')
        is_price_lvl = False
        attr_price_lvl_id = None
        if 'price_lvl' in self.attribute:
            is_price_lvl = True
            attr_currency = tmp[-1]
            attr_price_lvl_id = int(tmp[-4].partition('(')[-1].rpartition(')')[0])
            attr_tax_ratio = tmp[-5]
        else:
            attr_currency = tmp[-1]
            attr_tax_ratio = tmp[-2]

        attr_tax_ratio = Decimal(attr_tax_ratio)
        value = self.clean(data)

        if value is '' or value is None:
            return
        else:
            value = Decimal(value)
            related_object_type = ContentType.objects.get_for_model(obj)

            price, created = Price.objects.update_or_create(
                content_type_id=related_object_type.id,
                object_id=obj.id,
                currency=Currency.objects.get(code=attr_currency),
                tax_ratio=TaxRatio.objects.get(percentage=attr_tax_ratio),
                price_level=PriceLevel.objects.get(pk=attr_price_lvl_id) if is_price_lvl else None,
                defaults={'_price_excluding_tax': value}
            )


class CarouselImageField(Field):

    def save(self, obj, data):

        values = self.clean(data)
        obj.carousel_images.clear()
        for image in values:

            related_object_type = ContentType.objects.get_for_model(obj)

            carousel_image = CarouselImages(
                content_type_id=related_object_type.id,
                object_id=obj.id,
                image=image
            )
            obj.carousel_images.add(carousel_image, bulk=False)


class AttributeField(Field):
    def get_value(self, obj):

        if self.attribute is None or obj.is_parent:
            return None

        tmp = self.attribute.split('__')
        attr_id = int(tmp[1].partition('(')[-1].rpartition(')')[0])

        try:
            att_value = obj.option_values.get(group_id=attr_id)

        except (ValueError, ObjectDoesNotExist):
            return None

        return att_value.value.name

    def save(self, obj, data):
        if not self.readonly:
            tmp = self.attribute.split('__')
            attr_id = int(tmp[1].partition('(')[-1].rpartition(')')[0])
            is_active = False if 'notactive' in tmp[1] else True
            value = self.clean(data)

            if value is '' or value is None:
                return
            else:
                group = AttributeOptionGroup.objects.get(id=attr_id, is_active=is_active)
                attr_option = AttributeOption.objects.filter(product_class=obj.product_class, group=group, name=value)
                if attr_option.count() == 0:
                    attr_option = AttributeOption(
                        product_class=obj.product_class,
                        group=group,
                        name=value
                    )
                    attr_option.save()
                else:
                    attr_option = attr_option.first()

                attr, created = AttributeOptionGroupValue.objects.update_or_create(
                    product=obj,
                    group=group,
                    defaults={'value': attr_option},
                )


class ParentField(Field):
    def get_value(self, obj):

        try:
            if not obj.get_parent():
                return ''

            with switch_language(obj, 'sk'):
                with switch_language(obj.get_parent(), 'sk'):
                    parent_slug = obj.get_parent().slug
                    return parent_slug

        except (ValueError, ObjectDoesNotExist):
            return None

    def save(self, obj, data):
        """
        If this field is not declared readonly, the object's attribute will
        be set to the value returned by :meth:`~import_export.fields.Field.clean`.
        """
        if not self.readonly:
            value = self.clean(data)

            if obj.is_parent or value is '' or value is None:
                if obj.id is None:
                    obj.add_root(instance=obj)
                else:
                    return
            else:
                translation.activate('sk')
                parent_obj = None
                try:
                    parent_obj = Product.objects.get(translations__slug=value)
                except Exception as e:
                    raise ValueError('ERROR: in product: "{}" - Parent slug: "{}" DOES NOT EXIST'.format(obj.name, value))

                if obj not in parent_obj.get_children():
                    if obj.get_parent() is None:
                        obj.id = None
                        parent_obj.add_child(instance=obj)
                    else:
                        obj.move(parent_obj, 'last-child')
