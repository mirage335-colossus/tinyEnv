#!/usr/bin/env python3
"""Real loopback sessions, portable pipe cleanup, and protocol identity checks."""
import importlib.util
import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

spec=importlib.util.spec_from_file_location('server',sys.argv[1])
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
host=server.boundary.Host(('127.0.0.1',0),sys.argv[2])
thread=threading.Thread(target=host.serve_forever);thread.start()
base='http://'+host.authority

def post(path,payload,token=None,origin=None):
    headers={'Content-Type':'application/json','Origin':origin or base}
    if token:headers['X-Gui-Token']=token
    request=urllib.request.Request(base+path,json.dumps(payload).encode(),headers)
    with urllib.request.urlopen(request,timeout=20) as response:return json.load(response)

try:
    with urllib.request.urlopen(base,timeout=10) as response:
        assert b'renderer' in urllib.request.urlopen(base+'/boot.mjs',timeout=10).read()
        assert response.status==200
    created=post('/api/session',{});other=post('/api/session',{})
    token,state=created['token'],created['state'];sequence=0
    def widget(name):return next(v for v in state['snapshot']['widgets'] if v['key']['id']==name)
    def send(operation):
        global sequence,state
        sequence+=1
        state=post('/api/event',{'epoch':state['epoch'],'seq':str(sequence),'operation':operation},token)
        assert state['error']=='',state['error']
    send({'type':'edit','key':widget('entries.editor')['key'],'base':'','value':'Hosted entry'})
    send({'type':'activate','key':widget('entries.add')['key']})
    assert widget('entries.list')['records'][0]['text']=='Hosted entry'
    duplicate=post('/api/event',{'epoch':state['epoch'],'seq':str(sequence),'operation':{'type':'activate','key':widget('entries.add')['key']}},token)
    assert duplicate['error'] and len(widget('entries.list')['records'])==1
    isolated=next(v for v in other['state']['snapshot']['widgets'] if v['key']['id']=='entries.list')
    assert isolated['records']==[]
    send({'type':'choose','key':widget('entries.options')['key'],'id':'heading'})
    send({'type':'service','id':state['service']['id'],'status':'cancelled','value':'','error':''})
    assert widget('entries.heading')['text']=='Entry list'
    try:post('/api/session',{},origin='http://invalid.example')
    except urllib.error.HTTPError as error:assert error.code==403
    else:raise AssertionError('Foreign origin accepted')
    children=list(host.sessions.values())
    assert post('/api/release',{},token)['released']
    assert children[0].process.poll() is not None and not children[0].worker.is_alive()
finally:
    host.shutdown();thread.join(timeout=5);host.server_close()
assert all(s.process.poll() is not None and not s.worker.is_alive() for s in children)
# A child that exits immediately must not leave its worker or pipes alive.
try:server.Session(sys.executable)
except RuntimeError:pass
else:raise AssertionError('Invalid child protocol accepted')
print('Hosted browser assets, isolated sessions, action retry, services, origin and child cleanup passed')
