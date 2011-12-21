import os, shutil, copy, re

from django.test import TestCase
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db.models import Count

from swallow.config import DefaultConfig
from swallow.wrappers import XmlWrapper
from swallow.populator import BasePopulator
from swallow.models import Matching
from swallow.tests import Section, Article, ArticleToSection
from swallow.builder import BaseBuilder


CURRENT_PATH = os.path.dirname(__file__)


class ArticleWrapper(XmlWrapper):

    @property
    def instance_filters(self):
        return {'title': self.title}

    @property
    def modified_by(self):
        return 'swallow'


class ArticlePopulator(BasePopulator):

    _fields_one_to_one = ('title', 'author', 'modified_by')
    _fields_if_instance_already_exists = (
        'sections',
        'primary_sections',
        'kind',
        'author',
    )
    _fields_if_instance_modified_from_last_import = (
        'sections',
        'primary_sections',
    )

    def kind(self):
        self._from_matching(
            'SOURCES',
            'kind'
        )

    def sections(self):
        self._from_matching(
            'SECTIONS',
            'sections',
            create_through=self.create_article_to_section,
            get_or_create_related=self.get_or_create_section_from_name,
        )

    def primary_sections(self):
        self._from_matching(
            'SECTIONS',
            'primary_sections',
            first_matching=True,
            get_or_create_related=self.get_or_create_section_from_name,
        )

    def get_or_create_section_from_name(self, name):
        section, created = Section.objects.get_or_create(name=name)
        return section, created

    def create_article_to_section(self, section):
        through = ArticleToSection(
            article=self._instance,
            section=section,
            weight=self._wrapper.weight,
        )
        through.save()
        return through


class ArticleBuilder(BaseBuilder):

    Wrapper = ArticleWrapper
    Model = Article
    Populator = ArticlePopulator

    def __init__(self, path, fd):
        super(ArticleBuilder, self).__init__(path, fd)

    def skip(self, wrapper):
        return False

    def instance_is_modified(self, instance):
        if instance.modified_by is None:
            return False
        return instance.modified_by == 'swallow'


class ArticleConfig(DefaultConfig):

    def builder(self, path, fd):
        filename = os.path.basename(path)
        if re.match(r'^\w+\.xml$', filename) is not None:
            return ArticleBuilder(path, fd)
        return None

    def instance_is_modified(self, instance):
        if instance.modified_by is None:
            return False
        else:
            return instance.modified_by != 'swallow'


expected_values_initial = {
    'Article Ski': {
        'kind':'DEPECHE',
        'sections': ['SPORT', 'SPORT INDIVIDUEL', 'SPORT DE GLISSE'],
        'weight': 10,
        'primary_section': 'SPORT',
        'author': 'MrFoo',
    },
    'Article Boxe': {
        'kind':'DEPECHE',
        'sections': ['SPORT', 'SPORT INDIVIDUEL'],
        'weight': 20, 
        'primary_section': 'SPORT',
        'author': 'MrFoo',
    },
    'Article Bilboquet': {
        'kind':'ARTICLE',
        'sections': ['SPORT'],
        'weight': 30,
        'primary_section': 'SPORT',
        'author': 'MrFoo',
    },
}

expected_values_after_update = copy.deepcopy(expected_values_initial)
expected_values_after_update['Article Ski']['weight'] = 100
expected_values_after_update['Article Ski']['author'] = 'MrF'
expected_values_after_update['Article Boxe']['weight'] = 200
expected_values_after_update['Article Boxe']['author'] = 'MrF'
expected_values_after_update['Article Bilboquet']['weight'] = 300
expected_values_after_update['Article Bilboquet']['author'] = 'MrF'
expected_values_after_update['Article Bilboquet']['sections'] = ['FUN']
expected_values_after_update['Article Bilboquet']['primary_section'] = 'FUN'

expected_values_after_update_with_modification = copy.deepcopy(expected_values_after_update)
expected_values_after_update_with_modification['Article Ski']['author'] = 'godzilla'
expected_values_after_update_with_modification['Article Boxe']['author'] = 'godzilla'
expected_values_after_update_with_modification['Article Bilboquet']['author'] = 'godzilla'


class IntegrationTests(TestCase):

    def setUp(cls):
        import_dir = os.path.join(CURRENT_PATH, 'import')
        if os.path.exists(import_dir):
            shutil.rmtree(import_dir)
        import_initial = os.path.join(CURRENT_PATH, 'import.initial')
        shutil.copytree(import_initial, import_dir)

        settings.MEDIA_ROOT = '/tmp'
        settings.SWALLOW_DIRECTORY = os.path.join(CURRENT_PATH, 'import')
        matching = Matching(name='SECTIONS')
        f = open(os.path.join(CURRENT_PATH, 'sections.xml'))
        content = f.read()
        f.close()
        matching.file.save(
            'swallow/sections.xml',
            ContentFile(content),
            save=True
        )

        matching = Matching(name='SOURCES')
        f = open(os.path.join(CURRENT_PATH, 'sources.xml'))
        content = f.read()
        f.close()
        matching.file.save(
            'swallow/sources.xml',
            ContentFile(content),
            save=True
        )

    def _test_articles(self, expected_values):
        self.assertEqual(3, Article.objects.count())

        for article in Article.objects.all():
            self.assertIn(article.title, expected_values.keys())

            # expected value for this article
            expected_value = expected_values[article.title]

            # check kind
            self.assertEqual(expected_value['kind'], article.kind)

            # check author
            self.assertEqual(expected_value['author'], article.author)

            # check weight
            for through in article.articletosection_set.all():
                self.assertEqual(expected_value['weight'], through.weight)

            # check sections
            self.assertEqual(
                len(expected_value['sections']),
                article.sections.count()
            )

            for section in article.sections.all():
                self.assertIn(section.name, expected_value['sections'])

            # check primary sections
            self.assertEqual(1, article.primary_sections.count())

            self.assertEqual(
                expected_value['primary_section'],
                article.primary_sections.all()[0].name
            )

        self._test_no_multiple_insert_of_sections()

    def _test_no_multiple_insert_of_sections(self):
        aggregates = Section.objects.values('name').annotate(count=Count('name'))
        for aggregate in aggregates:
            self.assertEqual(1, aggregate['count'])

    def _update_imports(self):
        # simulate an update
        import_dir = os.path.join(CURRENT_PATH, 'import')
        shutil.rmtree(import_dir)
        import_update = os.path.join(CURRENT_PATH, 'import.update')
        shutil.copytree(import_update, import_dir)

    def test_run_without_command(self):
        """Tests full configuration without commands"""
        config = ArticleConfig()
        config.run()

        self._test_articles(expected_values_initial)

    def test_run_with_update(self):
        """Check that update of instances is properly done"""
        config = ArticleConfig()
        # first import
        config.run()

        self._update_imports()

        # second import
        config.run()

        self._test_articles(expected_values_after_update)

    def test_run_with_update_and_modification(self):
        """Check that update is properly done when instances in db were
        modified"""
        config = ArticleConfig()
        config.run()

        # modify Articles
        for article in Article.objects.all():
            article.modified_by = 'user'
            article.author = 'godzilla'
            article.save()

        self._update_imports()

        # second import
        config.run()

        self._test_articles(expected_values_after_update_with_modification)

    def test_run_with_command(self):
        """Tests full configuration with command"""
        call_command(
            'swallow',
            'swallow.tests.integration.ArticleConfig'
        )

        self._test_articles(expected_values_initial)

    def tearDown(self):
        import_dir = os.path.join(CURRENT_PATH, 'import')
        shutil.rmtree(import_dir)