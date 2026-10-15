"""Exercise the shipped undo handler across an uncertain response, without a browser."""

import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

import pytest


def run_node(script, *args):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is only needed for this frontend regression test")
    source = Path(__file__).parents[1] / "backend/survey/review/static/app.js"
    # stderr distinguishes a stalled startup from a harness that began executing.
    script = (
        "console.error('Harness started:', process.version, process.platform, process.arch);\n"
        + script
    )
    timeout = 60
    started = time.monotonic()
    try:
        result = subprocess.run(
            [node, "-e", script, str(source), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
        reason = (
            f"exceeded the {timeout}s deadline"
            if isinstance(error, subprocess.TimeoutExpired)
            else f"exited with code {error.returncode}"
        )
        pytest.fail(
            f"Node harness {reason} after {time.monotonic() - started:.2f}s\n"
            f"Executable: {node}\nPlatform: {platform.platform()}\n"
            f"Case: {args}\nstdout: {error.stdout!r}\nstderr: {error.stderr!r}",
            pytrace=False,
        )
    return json.loads(result.stdout)


@pytest.mark.parametrize("failure", ["network", "server", "conflict"])
def test_undo_handler_retries_original_body_or_refreshes_definite_conflict(failure):
    script = r"""
const fs=require('fs'), vm=require('vm');
const source=fs.readFileSync(process.argv[1],'utf8'), failure=process.argv[2];
const functions=source.slice(source.indexOf('function requestBody('),source.indexOf('async function decide('))+
  source.slice(source.indexOf('async function undoSaved('),source.indexOf("$('session').onsubmit"));
let version='v1', opens=0, history=0, saved=null, calls=[];
const context={crypto:require('crypto'),current:{id:'item',version:'v1'},pending:null,pendingUndo:null,lastSaved:{},
  $:()=>({}),message:()=>{},showSync:()=>{},refreshQueue:async()=>{},
  openItem:async()=>{opens++;context.current={id:'item',version}},
  api:async(path,body)=>{
    calls.push({...body});
    if(calls.length===1){
      version='v2';
      const e=Error('Uncertain response');
      if(failure==='conflict'){e.status=409;throw e;}
      history++;saved={...body};
      if(failure==='server')e.status=500;
      throw e;
    }
    if(failure!=='conflict' && JSON.stringify(body)!==JSON.stringify(saved))throw Error('Retry changed request');
    if(failure==='conflict')history++;
    return {sync:{},replayed:failure!=='conflict'};
  }};
vm.createContext(context);vm.runInContext(functions,context);
(async()=>{
  try{await context.undoSaved('item','decision')}catch{}
  const retained=context.pendingUndo!==null;
  await context.undoSaved('item','decision');
  console.log(JSON.stringify({calls,opens,history,retained,cleared:context.pendingUndo===null}));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    evidence = run_node(script, failure)
    assert evidence["history"] == 1 and evidence["cleared"]
    first, second = evidence["calls"]
    if failure == "conflict":
        assert not evidence["retained"]
        assert first["request_id"] != second["request_id"]
        assert second["expected_version"] == "v2"
    else:
        assert evidence["retained"]
        assert first == second
        assert evidence["opens"] == 1


def test_entered_amendment_disables_accept_and_submits_correction():
    script = r"""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync(process.argv[1],'utf8');
const functions=source.slice(source.indexOf('function hasUnsavedCorrection('),source.indexOf('function showSync('))+
source.slice(source.indexOf('async function run('),source.indexOf('async function undoSaved('));
const accept={dataset:{action:'accept'}},correct={dataset:{action:'correct'}},controls=[accept,correct];
const nodes={correction:{value:'04'},saved:{replaceChildren(){},append(){}},'session-reminder':{}};
const messages=[],calls=[];
const context={current:{id:'item',version:'v1',field:{value:null},allowed_actions:['accept','correct']},
  signedIn:true,scanReady:true,busy:false,pending:null,pendingUndo:null,lastSaved:null,crypto:require('crypto'),
  $:id=>nodes[id]||(nodes[id]={}),message:(text,error)=>messages.push({text,error}),showSync(){},refreshQueue:async()=>{},
  document:{querySelectorAll:s=>s==='[data-action]'?[accept,correct]:controls,
    querySelector:()=>accept,createElement:()=>({}),createTextNode:text=>({text})},
  api:async(path,body)=>{calls.push(body);return {item:{id:'item'},decision:{id:'decision'},sync:{}}}};
vm.createContext(context);vm.runInContext(functions,context);
(async()=>{
  context.setBusy(false);
  const acceptDisabled=accept.disabled,correctDisabled=correct.disabled;
  await context.decide('accept');
  const acceptanceCalls=calls.length;
  await context.decide('correct');
  const error=Error('Already recorded');error.code='no_op';
  await context.run(async()=>{throw error});
  console.log(JSON.stringify({acceptDisabled,correctDisabled,acceptanceCalls,calls,messages}));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    evidence = run_node(script)
    assert evidence["acceptDisabled"] and not evidence["correctDisabled"]
    assert evidence["acceptanceCalls"] == 0
    assert evidence["calls"][0]["action"] == "correct"
    assert evidence["calls"][0]["value"] == "04"
    assert "Save correction" in evidence["messages"][0]["text"]
    assert evidence["messages"][-1]["error"] is False
