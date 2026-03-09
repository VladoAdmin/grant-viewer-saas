export default function Help() {
  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Pomoc a návod</h1>

      <div className="space-y-6">
        {/* What is Grant Viewer */}
        <section className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">📋 Čo je Grant Viewer?</h2>
          <p className="text-sm text-gray-700 leading-relaxed">
            Grant Viewer je nástroj na prehľadávanie a vyhľadávanie v grantových výzvach
            z portálu ITMS21 a ďalších zdrojov. Automaticky zbiera výzvy, extrahuje dôležité
            informácie z príloh (PDF dokumenty) a umožňuje inteligentné vyhľadávanie v ich obsahu.
          </p>
        </section>

        {/* Browsing calls */}
        <section className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">📄 Prehľad výziev</h2>
          <ul className="text-sm text-gray-700 space-y-2 list-disc list-inside">
            <li>Na hlavnej stránke nájdete zoznam všetkých otvorených výziev</li>
            <li>Každá karta zobrazuje názov, vyhlasovateľa, deadline a alokáciu</li>
            <li>Kliknutím na kartu zobrazíte detail výzvy s kompletným prehľadom</li>
            <li>Použite filtre na zúženie výsledkov podľa zdroja, dátumu alebo kľúčových slov</li>
          </ul>
        </section>

        {/* Search */}
        <section className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">🔍 Kontextové vyhľadávanie</h2>
          <p className="text-sm text-gray-700 mb-3">
            Vyhľadávanie funguje na princípe sémantického hľadania, t.j. rozumie významu
            vašej otázky, nie len kľúčovým slovám. Môžete sa pýtať bežným jazykom.
          </p>
          <div className="bg-blue-50 rounded-md p-4">
            <p className="text-xs font-medium text-blue-700 mb-2">Príklady otázok:</p>
            <ul className="text-sm text-blue-700 space-y-1">
              <li>• "Kto môže žiadať o dotáciu na energetiku?"</li>
              <li>• "Podmienky pre neziskové organizácie"</li>
              <li>• "Maximálna výška príspevku"</li>
              <li>• "Hodnotiace kritériá pre projekty"</li>
              <li>• "Oprávnené náklady na rekonštrukciu budov"</li>
            </ul>
          </div>
        </section>

        {/* PDF Export */}
        <section className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">📄 Export do PDF</h2>
          <p className="text-sm text-gray-700">
            Na detaile výzvy nájdete tlačidlo "Stiahnuť PDF", ktoré vygeneruje súhrnný
            dokument s kľúčovými informáciami o výzve, vrátane vyhlasovateľa, alokácie,
            deadlinu, oprávnených žiadateľov a ďalších údajov.
          </p>
        </section>

        {/* Feedback */}
        <section className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">💬 Podnety a opravy</h2>
          <p className="text-sm text-gray-700">
            Ak nájdete chybu v údajoch alebo máte návrh na zlepšenie, kliknite na
            tlačidlo "Podnet" na detaile výzvy. Vaša spätná väzba nám pomáha
            zlepšovať kvalitu údajov.
          </p>
        </section>

        {/* Data sources */}
        <section className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">🌐 Zdroje údajov</h2>
          <div className="text-sm text-gray-700 space-y-2">
            <div className="flex items-center gap-3">
              <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded text-xs font-medium w-32 text-center">
                portal.itms21.sk
              </span>
              <span>ITMS21 — Informačný a monitorovací systém pre štrukturálne fondy EÚ</span>
            </div>
          </div>
          <p className="text-xs text-gray-500 mt-4">
            Údaje sa aktualizujú automaticky. Posledný stav scrapovania nájdete v sekcii Admin.
          </p>
        </section>

        {/* Contact */}
        <section className="bg-gray-50 rounded-lg border border-gray-200 p-6 text-center">
          <p className="text-sm text-gray-600">
            Máte otázky? Kontaktujte nás na{' '}
            <a href="mailto:info@stormlevel.sk" className="text-blue-600 hover:underline">
              info@stormlevel.sk
            </a>
          </p>
        </section>
      </div>
    </div>
  );
}
