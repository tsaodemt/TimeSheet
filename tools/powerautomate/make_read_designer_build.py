"""Generate a Playwright script that builds SPIKE-TS-ReadEntries in the Power Automate classic designer
(trigger inputs + variable inits + 'Guard' scope via clipboard paste) and saves it.

Configuration (environment variables): TS_PP_ENVIRONMENT, TS_CONN_SHAREPOINT, TS_CONN_O365USERS, TS_REQUIRED_INPUTS,
TS_CONN_O365GROUPS, TS_BUILD_SCRIPT_OUT, TS_FLOW_MODULE (default build_read_flow), TS_FLOW_NAME,
plus those of the flow module. Output is generated; do not commit.
"""
import copy, importlib, json, os, sys, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
r = importlib.import_module(os.environ.get("TS_FLOW_MODULE", "build_read_flow"))  # e.g. build_identity_flow

CONNS = {"shared_sharepointonline": os.environ.get("TS_CONN_SHAREPOINT", "<sharepoint-connection-id>"),
         "shared_office365users": os.environ.get("TS_CONN_O365USERS", "<office365users-connection-id>"),
         "shared_office365groups": os.environ.get("TS_CONN_O365GROUPS", "<office365groups-connection-id>")}
ENV = os.environ.get("TS_PP_ENVIRONMENT", "<power-platform-environment-id>")
OUT = os.environ.get("TS_BUILD_SCRIPT_OUT", "build_read_flow.js")
NAME = os.environ.get("TS_FLOW_NAME", "SPIKE-TS-ReadEntries")
REQUIRED = int(os.environ.get("TS_REQUIRED_INPUTS", "3"))  # leading trigger inputs left required

items, labels = [], []
for k, v in r.inits.items():
    d = copy.deepcopy(v); d["runAfter"] = {}
    items.append({"id": str(uuid.uuid4()), "brandColor": "#770BD6", "connectionReferences": {}, "connectorDisplayName": "Variables",
                  "icon": "", "isTrigger": False, "operationName": k, "operationDefinition": d})
    labels.append(k.replace("_", " "))
items.append({"id": str(uuid.uuid4()), "brandColor": "#8C3900",
              "connectionReferences": {k: {"connection": {"id": "/providers/Microsoft.PowerApps/apis/%s/connections/%s" % (k, v)}} for k, v in CONNS.items()},
              "connectorDisplayName": "Control", "icon": "", "isTrigger": False, "operationName": "Guard",
              "operationDefinition": {"type": "Scope", "actions": copy.deepcopy(r.guard), "runAfter": {}}})
labels.append("Guard")

JS = """async (page) => {
  const ctx = page.context().browser().contexts()[1];
  const pA = ctx.pages()[0];
  await ctx.grantPermissions(['clipboard-read','clipboard-write'], {origin:'https://make.powerautomate.com'});
  const ITEMS = %(items)s;
  const LABELS = %(labels)s;
  const INPUTS = %(inputs)s;
  const log = [];
  await pA.goto('https://make.powerautomate.com/environments/%(env)s/flows/new?newFlowName=%(name)s&trigger=providers%%2FMicrosoft.ProcessSimple%%2FoperationGroups%%2FFlow%%2Foperations%%2FFlowButton&v3=false');
  await pA.waitForTimeout(20000);
  await pA.bringToFront();
  const fb = pA.getByRole('button', {name: 'Close'}); if (await fb.count()) { await fb.first().click().catch(()=>{}); }
  await pA.keyboard.press('Escape');
  await pA.getByText('Manually trigger a flow').first().click(); await pA.waitForTimeout(2500);
  for (const inp of INPUTS) {
    await pA.getByText('Add an input').first().click(); await pA.waitForTimeout(1500);
    await pA.locator('div.msla-menu-item-logo[aria-label="' + inp[0] + '"]').first().click(); await pA.waitForTimeout(1500);
  }
  const add = await pA.getByText('Add an input').first().boundingBox();
  const n = INPUTS.length;
  const y0 = add.y + add.height/2 - n*75;
  for (let i = 0; i < n; i++) {
    const y = y0 + i*75;
    await pA.mouse.click(635, y); await pA.keyboard.press('Control+A'); await pA.keyboard.type(INPUTS[i][1]); await pA.waitForTimeout(250);
    await pA.mouse.click(870, y); await pA.keyboard.press('Control+A'); await pA.keyboard.type(INPUTS[i][2]); await pA.waitForTimeout(250);
  }
  for (let i = %(required)d; i < n; i++) {
    await pA.mouse.click(1080, y0 + i*75); await pA.waitForTimeout(1000);
    const opt = pA.getByText('Make the field optional'); if (await opt.count()) { await opt.first().click(); log.push('optional ' + INPUTS[i][1]); }
    await pA.waitForTimeout(600);
  }
  for (let i = 0; i < ITEMS.length; i++) {
    await pA.evaluate(t => navigator.clipboard.writeText(t), ITEMS[i]);
    await pA.getByText('New step', {exact:false}).last().click(); await pA.waitForTimeout(3000);
    const tab = pA.getByText('My clipboard'); if (await tab.count()) { await tab.first().click(); await pA.waitForTimeout(1500); }
    await pA.keyboard.press('Control+V'); await pA.waitForTimeout(3000);
    await pA.getByText(LABELS[i], {exact:true}).last().click(); await pA.waitForTimeout(4000);
    log.push('pasted ' + LABELS[i]);
  }
  await pA.getByText('Save', {exact:true}).last().click(); await pA.waitForTimeout(30000);
  const lines = (await pA.evaluate(() => document.body.innerText)).split(String.fromCharCode(10));
  const m = lines.filter(l => l.includes('rror') || l.includes('invalid') || l.includes('failed') || l.includes('ready') || l.includes('parse'));
  log.push(pA.url());
  log.push(JSON.stringify(m.slice(0, 20)));
  return log.join(' | ');
}""" % {"items": json.dumps([json.dumps(i) for i in items]), "labels": json.dumps(labels),
        "inputs": json.dumps(r.INPUTS), "env": ENV, "name": NAME, "required": REQUIRED}

open(OUT, "w", encoding="utf-8").write(JS)
print(OUT, len(JS))
