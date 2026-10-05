"""Generate one Playwright script that builds SPIKE-TS-SaveEntry from scratch in the classic designer
(trigger inputs + 3 variable inits + Guard scope via clipboard paste) and saves it.
Output: <playwright-mcp dir>/build_flow.js (generated; do not commit)."""
import copy, json, sys, os, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_guard_flow as b  # noqa: E402

CONNS = {"shared_sharepointonline": os.environ.get("TS_CONN_SHAREPOINT", "<sharepoint-connection-id>"),
         "shared_office365users": os.environ.get("TS_CONN_O365USERS", "<office365users-connection-id>"),
         "shared_office365groups": os.environ.get("TS_CONN_O365GROUPS", "<office365groups-connection-id>")}
OUT = os.environ.get("TS_BUILD_SCRIPT_OUT", "build_flow.js")
ENV = os.environ.get("TS_PP_ENVIRONMENT", "<power-platform-environment-id>")

acts = copy.deepcopy(b.actions)
items = []
for n in ["Init_ItemId", "Init_WriteLog", "Init_WriteOk"]:
    d = copy.deepcopy(acts[n]); d["runAfter"] = {}
    items.append({"id": str(uuid.uuid4()), "brandColor": "#770BD6", "connectionReferences": {}, "connectorDisplayName": "Variables",
                  "icon": "", "isTrigger": False, "operationName": n, "operationDefinition": d})
rest = {k: v for k, v in acts.items() if not k.startswith("Init_")}
rest["Get_caller_profile"]["runAfter"] = {}
items.append({"id": str(uuid.uuid4()), "brandColor": "#8C3900",
              "connectionReferences": {k: {"connection": {"id": "/providers/Microsoft.PowerApps/apis/%s/connections/%s" % (k, v)}} for k, v in CONNS.items()},
              "connectorDisplayName": "Control", "icon": "", "isTrigger": False, "operationName": "Guard",
              "operationDefinition": {"type": "Scope", "actions": rest, "runAfter": {}}})
labels = ["Init ItemId", "Init WriteLog", "Init WriteOk", "Guard"]

JS = """async (page) => {
  const ctx = page.context().browser().contexts()[1];
  const pA = ctx.pages()[0];
  await ctx.grantPermissions(['clipboard-read','clipboard-write'], {origin:'https://make.powerautomate.com'});
  const ITEMS = %(items)s;
  const LABELS = %(labels)s;
  const log = [];
  pA.once('dialog', d => d.accept().catch(()=>{}));
  await pA.goto('https://make.powerautomate.com/environments/%(env)s/flows/new?newFlowName=SPIKE-TS-SaveEntry&trigger=providers%%2FMicrosoft.ProcessSimple%%2FoperationGroups%%2FFlow%%2Foperations%%2FFlowButton&v3=false');
  await pA.waitForTimeout(20000);
  await pA.bringToFront();
  const fb = pA.getByRole('button', {name: 'Close'}); if (await fb.count()) { await fb.first().click().catch(()=>{}); }
  await pA.keyboard.press('Escape');
  await pA.getByText('Manually trigger a flow').first().click(); await pA.waitForTimeout(2500);
  const types = ['Text','Number','Number','Text','Text','Text'];
  for (const t of types) {
    await pA.getByText('Add an input').first().click(); await pA.waitForTimeout(1500);
    await pA.locator('div.msla-menu-item-logo[aria-label="' + t + '"]').first().click(); await pA.waitForTimeout(1500);
  }
  const rows = [['Action','save | approve'],['ItemId','0 = new entry'],['Hours','hours'],['OwnerUpn','requested owner (blank = self)'],['CallerUpn','DECOY - logged, never trusted'],['ClientRequestId','caller correlation token']];
  const add = await pA.getByText('Add an input').first().boundingBox();
  const y0 = add.y + add.height/2 - 6*75;
  for (let i = 0; i < 6; i++) {
    const y = y0 + i*75;
    await pA.mouse.click(635, y); await pA.keyboard.press('Control+A'); await pA.keyboard.type(rows[i][0]); await pA.waitForTimeout(250);
    await pA.mouse.click(870, y); await pA.keyboard.press('Control+A'); await pA.keyboard.type(rows[i][1]); await pA.waitForTimeout(250);
  }
  for (const i of [3,4,5]) {
    await pA.mouse.click(1080, y0 + i*75); await pA.waitForTimeout(1000);
    const opt = pA.getByText('Make the field optional'); if (await opt.count()) { await opt.first().click(); log.push('optional ' + i); }
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
  const m = lines.filter(l => l.includes('rror') || l.includes('invalid') || l.includes('failed') || l.includes('ready') || l.includes('Saving') || l.includes('parse'));
  log.push(pA.url());
  log.push(JSON.stringify(m.slice(0, 15)));
  return log.join(' | ');
}""" % {"items": json.dumps([json.dumps(i) for i in items]), "labels": json.dumps(labels), "env": ENV}

open(OUT, "w", encoding="utf-8").write(JS)
print(OUT, len(JS))
