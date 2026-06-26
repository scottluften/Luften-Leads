// Paste this into a Google Apps Script project bound to the tracking Sheet.
// The Sheet needs one tab named "Contacted" with header row:
// lead_id | contacted | contacted_by | contacted_at | note

function getSheet() {
  return SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Contacted');
}

function doGet(e) {
  const sheet = getSheet();
  const rows = sheet.getDataRange().getValues();
  const headers = rows.shift();
  const out = rows.map(row => {
    const obj = {};
    headers.forEach((h, i) => obj[h] = row[i]);
    return obj;
  });
  return ContentService.createTextOutput(JSON.stringify(out))
    .setMimeType(ContentService.MimeType.JSON);
}

// Sent as Content-Type: text/plain to avoid a CORS preflight (Apps Script
// web apps don't implement OPTIONS, so a preflighted request just fails).
function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  const { lead_id, contacted, contacted_by, note } = body;

  const sheet = getSheet();
  const data = sheet.getDataRange().getValues();
  const idCol = data[0].indexOf('lead_id');
  let rowIndex = -1;
  for (let i = 1; i < data.length; i++) {
    if (data[i][idCol] === lead_id) { rowIndex = i + 1; break; }
  }

  const now = new Date().toISOString();
  const rowValues = [lead_id, contacted, contacted_by || '', now, note || ''];

  if (rowIndex === -1) {
    sheet.appendRow(rowValues);
  } else {
    sheet.getRange(rowIndex, 1, 1, rowValues.length).setValues([rowValues]);
  }

  return ContentService.createTextOutput(JSON.stringify({ ok: true }))
    .setMimeType(ContentService.MimeType.JSON);
}
