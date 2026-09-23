import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from bs4 import BeautifulSoup
from src import pipeline
from src.config import settings
from src.lead_sources.housing import HousingSource
from streamlit.testing.v1 import AppTest


class HousingSourceTests(unittest.TestCase):
    def test_order_within_zip_before_expansion(self):
        calls=[]
        sources=[]
        for name in ['Zillow','Redfin','Realtor.com']:
            source=Mock();source.name=name
            source.search.side_effect=lambda zipcode, name=name, **kwargs: calls.append((zipcode,name)) or []
            sources.append(source)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pipeline,'search_zipcodes',return_value=iter([('33130',0),('33128',1)])), \
             patch.object(pipeline,'source_chain_for',return_value=sources), \
             patch.object(pipeline,'seen_key_set',return_value=set()), \
             patch.object(pipeline,'make_run_dir',return_value=Path(tmp)), \
             patch.object(pipeline,'OpenAIFloorRenderer'):
            with self.assertRaises(RuntimeError): pipeline.generate_leads('33130','houses',5)
        self.assertEqual(calls,[(z,n) for z in ['33130','33128'] for n in ['Zillow','Redfin','Realtor.com']])
        from src.lead_sources.web_research import PRIORITIES
        self.assertLess(PRIORITIES['houses'].index('Zillow'), PRIORITIES['houses'].index('Redfin'))
        self.assertLess(PRIORITIES['houses'].index('Redfin'), PRIORITIES['houses'].index('Realtor.com'))

    def test_landing_page_followed_but_not_emitted(self):
        source=HousingSource('Redfin')
        url='https://www.redfin.com/FL/Miami/123-Example-33130/home/12345'
        parsed=Mock(images=[1,2])
        with patch('src.lead_sources.housing.run_queries',return_value=[{'href':'https://www.redfin.com/zipcode/33130'}]), \
             patch('src.lead_sources.housing.fetch_soup',return_value=BeautifulSoup(f'<a href="{url}">Home</a>','html.parser')), \
             patch.object(source,'_parse_listing',return_value=parsed) as parser:
            self.assertEqual(source.search('33130',2),[parsed])
            parser.assert_called_once_with(url,'33130')

    def test_fetch_failure_is_not_no_listings(self):
        source=HousingSource('Realtor.com')
        with patch('src.lead_sources.housing.run_queries',return_value=[{'href':'https://www.realtor.com/realestateandhomes-detail/123-Example_M12345-67890'}]), \
             patch.object(source,'_parse_listing',side_effect=RuntimeError('blocked')):
            with self.assertRaisesRegex(RuntimeError,'could not be accessed'):
                source.search('33130',1)

    def test_miami_default(self):
        app=AppTest.from_file(str(settings.project_root/'app.py'),default_timeout=30).run()
        app.text_input[0].set_value(settings.app_password);app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.text_input[0].value,'33130')

if __name__=='__main__': unittest.main()
