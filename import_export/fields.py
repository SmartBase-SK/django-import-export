from __future__ import unicode_literals
from django.conf import settings
import logging
from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.db import DatabaseError
from django.utils import translation
from faker.providers import currency
from parler.utils.context import switch_language

from sbcore.loading import get_model
from . import widgets

from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.db.models.fields import NOT_PROVIDED
from django.db.models.manager import Manager

Product = get_model('catalog', 'Product')
""" :type:  core.catalog.models.Product"""
Price = get_model('pricing', 'Price')
""" :type:  core.pricing.models.Price"""
OldPrice = get_model('pricing', 'OldPrice')
""" :type:  core.pricing.models.OldPrice"""
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

logger = logging.getLogger(__name__)



class Field:
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

    :param saves_null_values: Controls whether null values are saved on the object
    """
    empty_values = [None, '']

    def __init__(self, attribute=None, column_name=None, widget=None,
                 default=NOT_PROVIDED, readonly=False, saves_null_values=True):
        self.attribute = attribute
        self.default = default
        self.column_name = column_name
        if not widget:
            widget = widgets.Widget()
        self.widget = widget
        self.readonly = readonly
        self.saves_null_values = saves_null_values

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
                           "columns are: %s" % (self.column_name, list(data)))

        # If ValueError is raised here, import_obj() will handle it
        value = self.widget.clean(value, row=data)

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

    def save(self, obj, data, is_m2m=False):
        """
        If this field is not declared readonly, the object's attribute will
        be set to the value returned by :meth:`~import_export.fields.Field.clean`.
        """
        if not self.readonly:
            attrs = self.attribute.split('__')
            for attr in attrs[:-1]:
                obj = getattr(obj, attr, None)
            if attrs[-1] is 'id':
                return
            else:
                cleaned = self.clean(data)
                if cleaned is not None or self.saves_null_values:
                    if  not is_m2m:
                        setattr(obj, attrs[-1], cleaned)
                    else:
                        getattr(obj, attrs[-1]).set(cleaned)

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

    def save(self, obj, data, is_m2m=False):
        # if we have translations model for obj we setting
        # attribute to this model e.g. obj.translations.slug
        # in case that we don't have translations model
        # we settings attribute to obj.slug
        # (this will be proceeded by django-parler) somehow
        if not self.readonly:
            tmp = self.attribute.split('_')
            attr_name = "_".join(tmp[:-1])
            attr_language = tmp[-1]
            with switch_language(obj, attr_language):
                translation.activate(attr_language)
                field = obj._meta.model.translations.field.model._meta.get_field(attr_name)
                translation_model = obj.translations.filter(language_code=attr_language).first()
                if not translation_model:
                    translation_model = obj
                if field.blank and not field.null and not field.is_relation:
                    if self.clean(data) is None:
                        setattr(translation_model, attr_name, '')
                    else:
                        setattr(translation_model, attr_name, self.clean(data))
                else:
                    if attr_name == 'slug' and not obj.get_slug and Product.objects.translated(slug=self.clean(data)).exists():
                        raise ValueError(
                            'ERROR: in item: "{}" - Slug: "{}" ALREADY EXISTS. Slug has to be UNIQUE!'.format(obj.name,
                                                                                                            self.clean(data)))
                    setattr(translation_model, attr_name, self.clean(data))
                if type(translation_model) is not type(obj):
                    translation_model.save()

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

    def save(self, obj, data, is_m2m=False):
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
            value = round(Decimal(value), 5)
            related_object_type = ContentType.objects.get_for_model(obj)

            if not obj.id:
                obj.save()
            price, created = Price.not_nullable.update_or_create(
                content_type_id=related_object_type.id,
                object_id=obj.id,
                currency=Currency.objects.get(code=attr_currency),
                tax_ratio=TaxRatio.objects.get(percentage=attr_tax_ratio),
                price_level=PriceLevel.objects.get(pk=attr_price_lvl_id) if is_price_lvl else None,
                defaults={'_price_excluding_tax': value}
            )


class OldPriceField(PriceField):
    def get_value(self, obj):

        if self.attribute is None:
            return None

        tmp = self.attribute.split('__')
        attr_currency = tmp[-1]
        attr_tax_ratio = tmp[-5] if 'price_lvl' in self.attribute else tmp[-2]
        try:
            price_obj = obj.old_prices.get(currency__code=attr_currency, tax_ratio__percentage=attr_tax_ratio)
            value = price_obj.price_excluding_tax()
            return value
        except (ValueError, ObjectDoesNotExist):
            return None

    def save(self, obj, data, is_m2m=False):
        tmp = self.attribute.split('__')
        attr_currency = tmp[-1]
        attr_tax_ratio = tmp[-5] if 'price_lvl' in self.attribute else tmp[-2]

        attr_tax_ratio = Decimal(attr_tax_ratio)
        value = self.clean(data)

        if value is '' or value is None:
            return
        else:
            value = Decimal(value)
            related_object_type = ContentType.objects.get_for_model(obj)

            price, created = OldPrice.objects.update_or_create(
                content_type_id=related_object_type.id,
                object_id=obj.id,
                currency=Currency.objects.get(code=attr_currency),
                tax_ratio=TaxRatio.objects.get(percentage=attr_tax_ratio),
                defaults={'_price_excluding_tax': value}
            )


class CarouselImageField(Field):

    def save(self, obj, data, is_m2m=False):
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
        except MultipleObjectsReturned:
            raise MultipleObjectsReturned('Export error exception. Product#id={}, attr_id={}'.format(obj.id, attr_id))

        return att_value.value.name

    def save(self, obj, data, is_m2m=False):
        if not self.readonly:
            tmp = self.attribute.split('__')
            attr_id = int(tmp[1].partition('(')[-1].rpartition(')')[0])
            is_active = False if 'notactive' in tmp[1] else True
            value = self.clean(data)

            if value is '' or value is None:
                return
            else:
                group = AttributeOptionGroup.objects.get(id=attr_id, is_active=is_active)
                attr_option = AttributeOption.objects.filter(product_class=obj.product_class, group=group, translations__name=value)
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

            for lang_short, lang_long in settings.LANGUAGES:
                with switch_language(obj, lang_short):
                    with switch_language(obj.get_parent(), lang_short):
                        parent_slug = obj.get_parent().slug
                        # return slug in language which is set FIRST in settings.LANGUAGES
                        return parent_slug

        except (ValueError, ObjectDoesNotExist):
            return None

    def save(self, obj, data, is_m2m=False):
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
                for lang_short, lang_long in settings.LANGUAGES:
                    with switch_language(obj, lang_short):
                        translation.activate(lang_short)

                        parent_obj = None
                        try:
                            parent_obj = Product.objects.translated(slug=value).first()
                        except Exception as e:
                            raise ValueError('ERROR: in product: "{}" - Parent slug: "{}" DOES NOT EXIST'.format(obj.name, value))

                        if obj not in parent_obj.get_children():
                            if obj.get_parent() is None:
                                obj.id = None
                                parent_obj.add_child(instance=obj)
                            else:
                                try:
                                    obj.move(Product.objects.translated(slug=value).first(), 'last-child')
                                    obj = Product.objects.get(pk=obj.id)
                                except AttributeError:
                                    # because TreeBeard
                                    Product.fix_tree()
                                    obj.move(Product.objects.translated(slug=value).first(), 'last-child')
                        # return after FIRST language in settings.LANGUAGES
                        return

