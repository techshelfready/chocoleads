import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from PIL import Image
from streamlit.testing.v1 import AppTest
from src.config import settings
from src.models import Lead, RoomSelection, CandidateImage
from src import pipeline
from src.geography import search_zipcodes
from src.image_pipeline import OpenAIFloorRenderer


def lead(number, zipcode='30126'):
    return Lead(lead_id=str(number),property_type='houses',address=f'{number} Test Street',
                source_site='Test', source_url=f'https://example.com/home/{number}',zipcode=zipcode)


class WorkflowTests(unittest.TestCase):
    def test_nearest_zip_order_and_validation(self):
        areas=list(search_zipcodes('30126'))
        self.assertEqual(areas[0],('30126',0.0))
        self.assertEqual(len(areas),len({z for z,d in areas}))
        self.assertEqual([d for z,d in areas],sorted(d for z,d in areas))
        self.assertLess(areas[1][1],10)
        for bad in ['abcde','123','00000']:
            with self.assertRaises(ValueError): list(search_zipcodes(bad))

    def test_expansion_replaces_unusable_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def render(item, folder):
                if item.lead_id=='2': return item
                item.selected_rooms=[]
                for i in range(2):
                    before=folder/f'b{i}.png'; after=folder/f'a{i}.png'
                    before.write_bytes(b'image');after.write_bytes(b'image')
                    item.selected_rooms.append(RoomSelection(before_image_url='https://example.com/photo',
                        before_local_path=str(before),after_local_path=str(after),room_label='Indoor room',style_label='Marble'))
                return item
            def folder(run,address):
                p=root/address;p.mkdir();return p
            source=Mock(name='source');source.name='Test'
            source.search.side_effect=[[lead(1),lead(2)], [lead(1),lead(3,'30106'),lead(4,'30106'),lead(5,'30106'),lead(6,'30106'),lead(7,'30106')]]
            with patch.object(pipeline,'search_zipcodes',return_value=iter([('30126',0),('30106',4),('30168',7)])), \
                 patch.object(pipeline,'source_chain_for',return_value=[source]), \
                 patch.object(pipeline,'seen_key_set',return_value=set()), \
                 patch.object(pipeline,'make_run_dir',return_value=root), \
                 patch.object(pipeline,'make_lead_dir',side_effect=folder), \
                 patch.object(pipeline,'OpenAIFloorRenderer') as renderer, \
                 patch.object(pipeline,'BrandedPDFReport') as pdf, \
                 patch.object(pipeline,'append_leads') as save:
                renderer.return_value.select_room_images.side_effect=lambda item, folder: render(item,folder).selected_rooms
                renderer.return_value.render_after_images.side_effect=render
                _,leads,_=pipeline.generate_leads('30126','houses',5)
                self.assertEqual([l.lead_id for l in leads],['1','3','4','5','6'])
                self.assertEqual(leads[1].zipcode,'30106')
                self.assertEqual(source.search.call_count,2)
                pdf.return_value.build.assert_called_once()
                save.assert_called_once()

    def test_shortfall_does_not_publish_report(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pipeline,'search_zipcodes',return_value=iter([('30126',0),('30106',4)])), \
             patch.object(pipeline,'source_chain_for',return_value=[type('EmptySource', (), {'name': 'Test', 'search': lambda self, *args, **kwargs: []})()]), \
             patch.object(pipeline,'seen_key_set',return_value=set()), \
             patch.object(pipeline,'make_run_dir',return_value=Path(tmp)), \
             patch.object(pipeline,'OpenAIFloorRenderer'), \
             patch.object(pipeline,'BrandedPDFReport') as pdf:
            with self.assertRaisesRegex(RuntimeError,'Only 0 of 5'):
                pipeline.generate_leads('30126','houses',5)
            pdf.assert_not_called()

    def test_outdoor_ambiguous_duplicates_and_house_pair_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def download(url,path):
                Image.new('RGB',(20,20),'red' if url.endswith('1') else 'blue').save(path)
            item=lead(1);item.images=[CandidateImage(url=f'https://example.com/{i}') for i in [1,2]]
            renderer=OpenAIFloorRenderer.__new__(OpenAIFloorRenderer)
            good=[dict(index=1,is_indoor=True,has_walls=True,visible_floor=True,room_kind='garage'),
                  dict(index=2,is_indoor=True,has_walls=True,visible_floor=True,room_kind='interior')]
            cases=[[],[good[0]], [good[0],dict(good[1],is_indoor=False)],
                   [good[0],dict(good[1],has_walls=False)], [good[0],dict(good[1],visible_floor=False)],
                   [good[0],dict(good[1],index=1)], [good[0],dict(good[1],room_kind='garage')]]
            with patch('src.image_pipeline.download_file',side_effect=download):
                for selected in cases:
                    renderer._vision_json=Mock(return_value={'selected':selected})
                    self.assertEqual(renderer.select_room_images(item,root),[])
                renderer._vision_json=Mock(return_value={'selected':good})
                self.assertEqual(len(renderer.select_room_images(item,root)),2)

    def test_result_survives_rerun_and_clears_on_new_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'report.pdf';path.write_bytes(b'%PDF-1.4 test')
            app=AppTest.from_file(str(settings.project_root / 'app.py'),default_timeout=30).run()
            app.text_input[0].set_value(settings.app_password);app.button[0].click().run()
            self.assertFalse(app.exception)
            app.text_input[0].set_value('30126').run()
            with patch('src.pipeline.generate_leads',return_value=('test',[lead(i) for i in range(5)],str(path))):
                app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.success)
            self.assertFalse(app.dataframe)
            self.assertFalse(app.expander)
            self.assertEqual(app.session_state['report_result']['count'],5)
            app.run()  # Equivalent server rerun formerly triggered by a report download.
            self.assertTrue(app.success)
            self.assertEqual(app.session_state['report_result']['pdf'],path.read_bytes())
            app.selectbox[1].set_value(6).run()
            self.assertFalse(app.success)
            with self.assertRaises(KeyError):
                app.session_state['report_result']


if __name__=='__main__': unittest.main()
