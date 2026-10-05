"""Generate a Playwright script that replaces the 'Guard' scope of an existing read flow (classic designer) and saves.
Configuration: TS_PP_ENVIRONMENT, TS_READ_FLOW_ID, TS_CONN_*, TS_BUILD_SCRIPT_OUT (+ build_read_flow.py vars)."""
import copy, json, os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_read_flow as r  # noqa: E402
CONNS = {"shared_sharepointonline": os.environ.get("TS_CONN_SHAREPOINT", "<sharepoint-connection-id>"),
         "shared_office365users": os.environ.get("TS_CONN_O365USERS", "<office365users-connection-id>"),
         "shared_office365groups": os.environ.get("TS_CONN_O365GROUPS", "<office365groups-connection-id>")}
ENV = os.environ.get("TS_PP_ENVIRONMENT", "<power-platform-environment-id>")
FLOW = os.environ.get("TS_READ_FLOW_ID", "<read-flow-id>")
OUT = os.environ.get("TS_BUILD_SCRIPT_OUT", "repaste_read_guard.js")
item = {"id": str(uuid.uuid4()), "brandColor": "#8C3900",
        "connectionReferences": {k: {"connection": {"id": "/providers/Microsoft.PowerApps/apis/%s/connections/%s" % (k, v)}} for k, v in CONNS.items()},
        "connectorDisplayName": "Control", "icon": "", "isTrigger": False, "operationName": "Guard",
        "operationDefinition": {"type": "Scope", "actions": copy.deepcopy(r.guard), "runAfter": {}}}
JS = """async (page) => {
  const ctx = page.context().browser().contexts()[1];
  const pA = ctx.pages()[0];
  await ctx.grantPermissions(['clipboard-read','clipboard-write'], {origin:'https://make.powerautomate.com'});
  await pA.goto('https://make.powerautomate.com/environments/%(env)s/flows/%(flow)s?v3=false');
  await pA.waitForTimeout(20000);
  const lines = async () => (await pA.evaluate(() => document.body.innerText)).split(String.fromCharCode(10));
  const g = pA.getByText('Guard', {exact:true}).first();
  const box = await g.boundingBox();
  await pA.mouse.click(box.x + 540, box.y + box.height/2); await pA.waitForTimeout(1500);
  const d = pA.getByText('Delete', {exact:true}); if (await d.count()) { await d.last().click(); await pA.waitForTimeout(1500); const ok = pA.getByRole('button',{name:'OK'}); if (await ok.count()) await ok.first().click(); await pA.waitForTimeout(2000); }
  if ((await lines()).includes('Guard')) return 'guard not deleted';
  await pA.evaluate(t => navigator.clipboard.writeText(t), %(item)s);
  await pA.getByText('New step', {exact:false}).last().click(); await pA.waitForTimeout(3000);
  const tab = pA.getByText('My clipboard'); if (await tab.count()) { await tab.first().click(); await pA.waitForTimeout(1500); }
  await pA.keyboard.press('Control+V'); await pA.waitForTimeout(3000);
  await pA.getByText('Guard', {exact:true}).last().click(); await pA.waitForTimeout(5000);
  await pA.getByText('Save', {exact:true}).last().click(); await pA.waitForTimeout(30000);
  const m = (await lines()).filter(l => l.includes('rror') || l.includes('invalid') || l.includes('failed') || l.includes('saved') || l.includes('ready'));
  return pA.url() + ' | ' + JSON.stringify(m.slice(0, 15));
}""" % {"env": ENV, "flow": FLOW, "item": json.dumps(json.dumps(item))}
open(OUT, "w", encoding="utf-8").write(JS)
print(OUT)
