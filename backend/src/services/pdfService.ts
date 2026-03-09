/**
 * PDF Service — generates PDF by calling the Python scraper's pdf_export module.
 * This delegates to the existing Python reportlab code.
 */

import { execFile } from 'child_process';
import path from 'path';
import fs from 'fs';
import os from 'os';
import { CallDetail } from './callService';

/**
 * Generate a PDF for a grant call by invoking the Python PDF generator.
 */
export async function generatePdf(detail: CallDetail): Promise<Buffer> {
  const tmpFile = path.join(os.tmpdir(), `grant-pdf-${Date.now()}.pdf`);
  const scraperDir = path.resolve(__dirname, '../../../scraper');

  // Write call data as JSON for the Python script to consume
  const inputFile = path.join(os.tmpdir(), `grant-input-${Date.now()}.json`);
  fs.writeFileSync(inputFile, JSON.stringify(detail));

  try {
    await new Promise<void>((resolve, reject) => {
      const pythonScript = `
import sys, json
sys.path.insert(0, '${scraperDir.replace(/'/g, "\\'")}')
sys.path.insert(0, '${path.resolve(scraperDir, '..').replace(/'/g, "\\'")}')

from scraper.pdf_export import generate_call_pdf

with open('${inputFile.replace(/'/g, "\\'")}', 'r') as f:
    data = json.load(f)

call = data.get('call', {})
attributes = data.get('attributes', {})
attachments = data.get('attachments', [])

pdf_bytes = generate_call_pdf(call, attributes, attachments)
if pdf_bytes:
    with open('${tmpFile.replace(/'/g, "\\'")}', 'wb') as f:
        f.write(pdf_bytes)
    print('OK')
else:
    print('FAIL: No PDF generated')
    sys.exit(1)
`;

      execFile('python3', ['-c', pythonScript], { timeout: 30000 }, (err, stdout, stderr) => {
        if (err) {
          reject(new Error(`PDF generation failed: ${stderr || err.message}`));
        } else if (stdout.trim().startsWith('FAIL')) {
          reject(new Error(stdout.trim()));
        } else {
          resolve();
        }
      });
    });

    const pdfBuffer = fs.readFileSync(tmpFile);
    return pdfBuffer;
  } finally {
    // Cleanup temp files
    try { fs.unlinkSync(tmpFile); } catch { /* ignore */ }
    try { fs.unlinkSync(inputFile); } catch { /* ignore */ }
  }
}
