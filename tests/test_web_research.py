import json
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
from src.lead_sources.web_research import WebResearchSource,zillow_property,zillow_images
from src.geography import search_zipcodes
from itertools import islice

class WebResearchTests(unittest.TestCase):
    def test_optional_nulls_do_not_discard_valid_industrial_lead(self):
        source=WebResearchSource('industrial properties')
        url='https://example.com/warehouse'
        response={'leads':[{'address':'100 NW 1st St, Miami, FL 33142','zipcode':'33142','source_url':url,
                            'title':None,'price':None,'size':None,'garage_photo_url':None}],
                  '_response_id':'test','_web_calls':[{'action':{'url':url}}]}
        with patch.object(source,'research',return_value=response):
            leads=source.search('33142',10)
        self.assertEqual(len(leads),1)
        self.assertEqual(leads[0].images,[])

    def test_wrong_zip_and_unobserved_sources_rejected(self):
        source=WebResearchSource('houses')
        response={'leads':[{'address':'33130 Test Road, Arizona 85266','zipcode':'85266','source_url':'https://example.com/observed'},
                           {'address':'100 Main St Miami 33130','zipcode':'33130','source_url':'https://example.com/invented'}],
                  '_response_id':'test','_web_calls':[{'url':'https://example.com/observed'}]}
        with patch.object(source,'research',return_value=response):
            self.assertEqual(source.search('33130',10),[])

    def test_full_zillow_gallery_only_for_matching_property(self):
        target={'zpid':123,'zipcode':'33130','homeType':'SINGLE_FAMILY','responsivePhotos':[
            {'caption':str(i),'mixedSources':{'jpeg':[{'width':192,'url':f'https://photos.example/{i}-small.jpg'},
                                                    {'width':1536,'url':f'https://photos.example/{i}.jpg'}]}} for i in range(40)]}
        related={'zpid':999,'responsivePhotos':[{'url':'https://wrong-property.example/other.jpg'}]}
        data={'props':{'gdpClientCache':json.dumps({'query':{'property':target,'related':related}})}}
        soup=BeautifulSoup('<script id="__NEXT_DATA__" type="application/json">'+json.dumps(data)+'</script>','html.parser')
        prop=zillow_property(soup,'https://www.zillow.com/homedetails/House/123_zpid/')
        images=zillow_images(prop,'https://www.zillow.com/homedetails/House/123_zpid/')
        self.assertEqual(len(images),40)
        self.assertEqual(images[-1].url,'https://photos.example/39.jpg')
        self.assertIsNone(zillow_property(soup,'https://www.zillow.com/homedetails/House/456_zpid/'))

    def test_miami_expansion_reaches_real_neighborhoods(self):
        neighbors=[z for z,_ in islice(search_zipcodes('33130'),13)]
        self.assertIn('33131',neighbors)
        self.assertIn('33135',neighbors)
        self.assertNotIn('33102',neighbors)
        self.assertNotIn('33269',neighbors)

if __name__=='__main__':unittest.main()
