"""Live, unmocked Streamlit end-to-end test. Uses configured APIs and real assets."""
import logging,json,sys
from pathlib import Path
from streamlit.testing.v1 import AppTest
from src.config import settings
logger=logging.getLogger('chocoleads');logger.setLevel(logging.INFO);logger.addHandler(logging.StreamHandler(sys.stdout))
kind=sys.argv[1] if len(sys.argv)>1 else 'commercial properties'
zipcode=sys.argv[2] if len(sys.argv)>2 else '33130'
app=AppTest.from_file(str(settings.project_root/'app.py'),default_timeout=3600).run()
assert not app.exception
app.text_input[0].set_value(settings.app_password);app.button[0].click().run()
app.selectbox[0].set_value(kind).run()
if not app.text_input[0].disabled:
    app.text_input[0].set_value(zipcode).run()
app.selectbox[1].set_value(5).run()
print('LIVE UI START',kind,zipcode,flush=True)
app.button[0].click().run(timeout=3600)
assert not app.exception, [e.message for e in app.exception]
if app.error:raise RuntimeError('; '.join(e.value for e in app.error))
result=app.session_state['report_result']
assert result['count']==5 and result['pdf'].startswith(b'%PDF-')
Path('work/live-e2e/'+kind.split()[0]+'-result.pdf').write_bytes(result['pdf'])
app.run()
assert app.session_state['report_result']['pdf']==result['pdf']
assert app.success
Path('work/live-e2e/'+kind.split()[0]+'-ui-result.json').write_text(json.dumps({'property_type':kind,'zipcode':zipcode,'lead_count':5,'report_filename':result['filename'],'pdf_bytes':len(result['pdf']),'session_persistence':'passed'},indent=2))
print('LIVE UI PASS',kind,result['filename'],len(result['pdf']),flush=True)
