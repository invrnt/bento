"""A small personal library shaped like the second real-model pass (39 files, `smart-search-real-model-pass-2`).

Files with text (text-layer PDFs, `.txt`, `.md`, `.csv`) carry it; scanned PDFs and PNGs have none, so with OCR
off they are embedded by file name only. All content is synthetic.
"""

from __future__ import annotations

PDF = "application/pdf"
PNG = "image/png"
TXT = "text/plain"
MD = "text/markdown"
CSV = "text/csv"

# (file name, mime type, document text or "" for files with no text layer)
FILES: list[tuple[str, str, str]] = [
    ("factura-luz-enero-2026.pdf", PDF, "Compañía Eléctrica del Sur. Factura de electricidad. Periodo de facturación: enero 2026. Potencia contratada 4,6 kW. Consumo 212 kWh. Importe total 61,20 €."),
    ("factura-luz-febrero-2026.pdf", PDF, "Compañía Eléctrica del Sur. Factura de electricidad. Periodo: febrero 2026. Consumo 198 kWh. Término de energía y de potencia. Importe total 58,75 €."),
    ("factura-agua-marzo-2026.pdf", PDF, "Aguas Municipales. Recibo del suministro de agua, bimestre enero-febrero 2026. Consumo 14 m³. Cuota de servicio y alcantarillado. Total 31,40 €."),
    ("factura-gas-natural-febrero.pdf", PDF, "Comercializadora de gas natural. Factura de gas del periodo de febrero. Consumo 420 kWh. Término fijo y variable. Importe 62,00 €."),
    ("phone-bill-january.pdf", PDF, "Mobile operator invoice, January 2026. Fibre 600 Mb and a mobile line with 50 GB. Total 45.00 EUR including VAT."),
    ("electric-bill-october-2025.pdf", PDF, "Electricity bill, October 2025. Northern Power Co. Usage 214 kWh. Standing charge and energy charge. Amount due 63.10 EUR."),
    ("water-bill-december-2025.pdf", PDF, "City Water. Water supply bill for November and December 2025. Usage 12 cubic metres. Amount due 29.80 EUR."),
    ("receta-pasta-carbonara.pdf", PDF, "Espaguetis a la carbonara. Ingredientes: 400 g de espaguetis, guanciale, yemas de huevo, pecorino romano y pimienta negra. Dorar el guanciale, mezclar la pasta con las yemas y el queso fuera del fuego."),
    ("receta-lasana-verduras.pdf", PDF, "Lasaña de verduras. Placas de lasaña, calabacín, berenjena, espinacas, salsa de tomate y bechamel. Montar capas y hornear 35 minutos a 190 grados."),
    ("pesto-pasta-recipe.pdf", PDF, "Pesto pasta. Blend fresh basil, pine nuts, garlic, parmesan and olive oil. Toss with linguine and a splash of the pasta water."),
    ("receta-gazpacho.pdf", PDF, "Gazpacho andaluz. Tomates maduros, pimiento verde, pepino, ajo, pan del día anterior, aceite de oliva, vinagre y sal. Triturar, colar y servir muy frío."),
    ("viaje-cadiz-playa-agosto.pdf", PDF, "Viaje a Cádiz en agosto. Apartamento a 200 metros de la playa de la Victoria. Días de playa en Bolonia y Zahara de los Atunes, puesta de sol en Caños de Meca."),
    ("reserva-hotel-mallorca.pdf", PDF, "Confirmación de reserva. Hotel frente al mar en Alcúdia, Mallorca. Llegada 12 de julio, salida 19 de julio. Habitación doble con vistas a la playa y desayuno."),
    ("beach-vacation-itinerary-hawaii.pdf", PDF, "Hawaii beach vacation itinerary. Day 1 Waikiki beach, day 2 snorkelling at Hanauma Bay, day 3 North Shore surf, day 4 Maui sunset at Kaanapali."),
    ("notas-reunion-presupuesto-q3.pdf", PDF, "Notas de la reunión de presupuesto del tercer trimestre. Asistentes: dirección y finanzas. Se recorta el gasto en marketing un 10 % y se aprueba la contratación de dos ingenieros."),
    ("budget-meeting-minutes.pdf", PDF, "Budget meeting minutes. Attendees: finance team and department heads. Agreed to freeze travel spending, move the hardware purchase to Q4 and review headcount in October."),
    ("contrato-alquiler-piso.pdf", PDF, "Contrato de arrendamiento de vivienda. El arrendador cede al arrendatario el piso de la calle Mayor 12 por una renta mensual de 850 euros, con una fianza de dos mensualidades."),
    ("annual-revenue-report-2025.pdf", PDF, "Annual revenue report 2025. Total revenue grew 18 % year over year, operating margin 22 %. Outlook for 2026: expand to two new markets."),
    ("doc-2026-0417.pdf", PDF, "Clínica veterinaria San Antón. Visita del 17 de abril. Paciente: Toby, perro mestizo de 3 años. Se administra la vacuna antirrábica y la desparasitación. Próxima revisión en un año."),
    ("escaneo-recibo-electricidad-marzo.pdf", PDF, ""),
    ("scan-0093.pdf", PDF, ""),
    ("endesa-recibo-abril.png", PNG, ""),
    ("captura-whatsapp-cena.png", PNG, ""),
    ("ticket-supermercado.png", PNG, ""),
    ("apuntes.txt", TXT, "La contraseña del wifi es Gaviota-2026. El router está detrás de la tele. Llamar al técnico si se corta la fibra."),
    ("notes-0312.txt", TXT, "Mortgage renewal: the bank offers a fixed interest rate of 2.9 % for 25 years. Compare with the variable rate before signing in April."),
    ("packing-list-beach.txt", TXT, "Packing list for the beach: swimsuit, sunscreen, towels, flip-flops, sunglasses, a beach umbrella and a cooler with drinks."),
    ("lista-compra.txt", TXT, "Lista de la compra: leche, huevos, pan, tomates, aceite de oliva, café, yogures, papel de cocina y detergente."),
    ("ideas-regalos-navidad.txt", TXT, "Ideas de regalos para Navidad: un libro de cocina para mamá, auriculares para Pablo, un puzle para los niños y una bufanda para la abuela."),
    ("diario-2026-02.txt", TXT, "Febrero. Semana dura en el trabajo, mucha tensión con el lanzamiento. El domingo fuimos a caminar por el monte y me despejé."),
    ("plan-mudanza.md", MD, "# Plan de mudanza\n\n- Pedir presupuesto a tres empresas de mudanzas\n- Dar de baja la luz y el agua del piso viejo\n- Empaquetar la cocina la última semana\n- Cambiar la dirección en el banco"),
    ("project-roadmap.md", MD, "# Project roadmap\n\n- Q1: offline sync and conflict resolution\n- Q2: Android app beta\n- Q3: search by meaning\n- Q4: shared family vaults"),
    ("receta-tortilla.md", MD, "# Tortilla de patatas\n\nCinco huevos, tres patatas grandes y una cebolla. Freír las patatas a fuego lento, mezclar con el huevo batido y cuajar por ambos lados."),
    ("hiking-notes.md", MD, "# Hiking notes\n\nTrail to the lake: 12 km, 600 m elevation gain. Bring water, a rain jacket and snacks. The last part is steep and rocky."),
    ("gastos-hogar-2026.csv", CSV, "mes,concepto,importe\nenero,alquiler,850\nenero,luz,61.20\nenero,agua,31.40\nfebrero,alquiler,850\nfebrero,luz,58.75\nfebrero,gas,62.00\nfebrero,internet,45.00"),
    ("reading-list.csv", CSV, "title,author,status\nThe Left Hand of Darkness,Ursula K. Le Guin,read\nDune,Frank Herbert,reading\nThe Name of the Rose,Umberto Eco,to read"),
    ("inventario-trastero.csv", CSV, "caja,contenido\n1,tienda de campaña y sacos de dormir\n2,adornos de Navidad\n3,herramientas y taladro\n4,ropa de invierno"),
    ("nota-taller.txt", TXT, "Taller mecánico: cambio de pastillas de freno delanteras y cambio de aceite. Revisar los neumáticos en 5.000 km. Total 240 €."),
    ("doc-2026-0601.pdf", PDF, "Dirección General de Tráfico. Notificación de denuncia por exceso de velocidad: 72 km/h en un tramo limitado a 50 km/h. Multa de 100 euros, sin pérdida de puntos."),
]

# The six queries of the second pass, then the misses it reported, then off-topic ones.
QUERIES: list[str] = [
    "facturas de luz",
    "receta de pasta",
    "viaje a la playa",
    "electricity bill",
    "reunión de presupuesto",
    "beach holiday",
    "car brakes repair",
    "speeding ticket",
    "vacuna del perro",
    "contraseña del wifi",
    "mortgage interest rate",
    "endesa",
    "zzzz quantum chromodynamics",
    "partitura de violonchelo barroco",
]

# The files each query is about, for nDCG@6 (binary relevance).
RELEVANT: dict[str, set[str]] = {
    "facturas de luz": {
        "factura-luz-enero-2026.pdf",
        "factura-luz-febrero-2026.pdf",
        "escaneo-recibo-electricidad-marzo.pdf",
        "endesa-recibo-abril.png",
        "electric-bill-october-2025.pdf",
    },
    "receta de pasta": {"receta-pasta-carbonara.pdf", "pesto-pasta-recipe.pdf", "receta-lasana-verduras.pdf"},
    "viaje a la playa": {
        "viaje-cadiz-playa-agosto.pdf",
        "reserva-hotel-mallorca.pdf",
        "beach-vacation-itinerary-hawaii.pdf",
        "packing-list-beach.txt",
    },
    "electricity bill": {
        "electric-bill-october-2025.pdf",
        "factura-luz-enero-2026.pdf",
        "factura-luz-febrero-2026.pdf",
        "escaneo-recibo-electricidad-marzo.pdf",
        "endesa-recibo-abril.png",
    },
    "reunión de presupuesto": {"notas-reunion-presupuesto-q3.pdf", "budget-meeting-minutes.pdf"},
    "beach holiday": {
        "beach-vacation-itinerary-hawaii.pdf",
        "packing-list-beach.txt",
        "viaje-cadiz-playa-agosto.pdf",
        "reserva-hotel-mallorca.pdf",
    },
    "car brakes repair": {"nota-taller.txt"},
    "speeding ticket": {"doc-2026-0601.pdf"},
    "vacuna del perro": {"doc-2026-0417.pdf"},
    "contraseña del wifi": {"apuntes.txt"},
    "mortgage interest rate": {"notes-0312.txt"},
    "endesa": {"endesa-recibo-abril.png"},
}


def ndcg_at(titles: list[str], relevant: set[str], k: int = 6) -> float:
    import math

    gains = sum(1.0 / math.log2(rank + 2) for rank, title in enumerate(titles[:k]) if title in relevant)
    ideal = sum(1.0 / math.log2(rank + 2) for rank in range(min(len(relevant), k)))
    return gains / ideal if ideal else 0.0
