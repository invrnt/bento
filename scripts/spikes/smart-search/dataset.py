"""Labelled retrieval fixture for the Stage 23 smart search spike.

~200 short documents shaped like what Bento indexes (OCR text of invoices, IDs,
recipes, travel, work, health, home, bank, school, photo metadata) and ~40 queries,
mostly Spanish, some English and cross-language. All content is synthetic.

`documents()` -> list of {id, title, text}; `queries()` -> list of {id, lang, q, relevant}.
"""

from __future__ import annotations

MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

HAND: list[tuple[str, str, str]] = [
    # Identity documents
    ("dni", "dni_frontal.jpg", "REINO DE ESPAÑA DOCUMENTO NACIONAL DE IDENTIDAD. Apellidos GARCÍA LÓPEZ Nombre MARÍA. Sexo F Nacionalidad ESP. Fecha de nacimiento 14 03 1988. Validez 22 07 2031. Número de soporte BAA123456."),
    ("pasaporte", "pasaporte_escaneado.pdf", "PASAPORTE PASSPORT. República de Colombia. Tipo P Código COL. Apellidos RODRÍGUEZ PÉREZ Nombres JUAN CARLOS. Fecha de expedición 05 MAY 2022 Fecha de vencimiento 04 MAY 2032. Lugar de nacimiento MEDELLÍN."),
    ("carnet-conducir", "carnet_conducir.jpg", "PERMISO DE CONDUCCIÓN. Dirección General de Tráfico. Clase B. Fecha de expedición 10.06.2015, válido hasta 10.06.2030. Restricciones: 01 lentes correctoras."),
    ("tarjeta-sanitaria", "tarjeta_sanitaria.png", "Tarjeta sanitaria individual. Servicio de Salud. Código de identificación personal SNS. Centro de salud asignado: Centro de Salud Las Delicias. Médico de familia: Dra. Ruiz."),
    ("nie", "tie_extranjero.jpg", "Tarjeta de Identidad de Extranjero. Residencia temporal y trabajo por cuenta ajena. NIE X1234567L. Válida hasta 18/11/2027."),
    ("cert-empadronamiento", "certificado_empadronamiento.pdf", "Ayuntamiento. Certificado de empadronamiento. Consta inscrito en el padrón municipal de habitantes en el domicilio Calle Mayor 12, 3º B desde el 02/02/2021."),
    ("visa-us", "visa_eeuu.pdf", "United States of America nonimmigrant visa. Visa type B1/B2. Entries M. Issue date 12JAN2024 Expiration date 10JAN2034. Annotation: none."),
    # Recipes
    ("receta-paella", "paella_valenciana.txt", "Paella valenciana. Ingredientes: arroz bomba, pollo, conejo, judía verde, garrofó, tomate, azafrán, aceite de oliva. Sofreír la carne, añadir verduras y agua, cocer el arroz 18 minutos sin remover hasta que se forme el socarrat."),
    ("receta-paella-marisco", "paella_marisco.txt", "Arroz con marisco para seis. Gambas, mejillones, calamar y almejas. Hacer un fumet con las cabezas de las gambas, sofrito de ñora y tomate, arroz y caldo de pescado caliente."),
    ("receta-tortilla", "tortilla.txt", "Tortilla de patatas de la abuela. Cinco huevos, tres patatas grandes, una cebolla. Freír las patatas a fuego lento, escurrir, mezclar con el huevo batido y cuajar por ambos lados."),
    ("receta-gazpacho", "gazpacho.txt", "Gazpacho andaluz. Tomates maduros, pimiento verde, pepino, ajo, pan del día anterior, aceite, vinagre y sal. Triturar todo, colar y servir muy frío."),
    ("receta-arepas", "arepas.txt", "Arepas de maíz. Harina de maíz precocida, agua tibia, sal y un poco de mantequilla. Amasar, formar discos y asar en budare hasta dorar. Rellenar con queso."),
    ("receta-ajiaco", "ajiaco_bogotano.txt", "Ajiaco santafereño. Tres tipos de papa (criolla, sabanera y pastusa), pollo, mazorca y guascas. Se sirve con crema de leche, alcaparras y aguacate."),
    ("receta-lentejas", "lentejas.txt", "Lentejas estofadas con chorizo. Remojar las lentejas, sofrito de cebolla, zanahoria y pimentón, añadir chorizo y patata y cocer cuarenta minutos."),
    ("receta-flan", "flan_casero.txt", "Flan de huevo casero. Hacer un caramelo con azúcar en el molde, batir huevos con leche y azúcar, hornear al baño maría a 170 grados durante 45 minutos."),
    ("receta-empanadas", "empanadas.txt", "Empanadas argentinas de carne cortada a cuchillo, cebolla, huevo duro y aceitunas. Repulgue a mano y horno fuerte veinte minutos."),
    ("receta-guacamole", "guacamole.txt", "Guacamole. Tres aguacates maduros, cebolla morada, cilantro, jalapeño, jugo de limón y sal. Machacar en molcajete."),
    ("receta-pancakes", "pancakes.md", "Fluffy pancakes. 1 cup flour, 1 tbsp sugar, 2 tsp baking powder, 1 egg, 1 cup milk, 2 tbsp melted butter. Cook on a hot griddle until bubbles form, then flip."),
    ("receta-banana-bread", "banana_bread.md", "Banana bread. Three overripe bananas, butter, brown sugar, one egg, flour, baking soda, a pinch of salt and walnuts. Bake at 175 C for one hour."),
    ("receta-brownies", "brownies.md", "Chocolate brownies. Melt dark chocolate with butter, whisk in sugar and eggs, fold in flour and cocoa. Bake 25 minutes; the center should stay fudgy."),
    ("receta-ceviche", "ceviche.txt", "Ceviche peruano. Corvina fresca en cubos, jugo de limón, ají limo, cebolla roja y cilantro. Servir con camote y choclo."),
    ("receta-bizcocho", "bizcocho_yogur.txt", "Bizcocho de yogur. Un yogur natural, tres medidas de harina, dos de azúcar, una de aceite, tres huevos y un sobre de levadura. Horno a 180 grados 35 minutos."),
    # Travel
    ("tarjeta-embarque-bogota", "boarding_pass_MAD_BOG.pdf", "Tarjeta de embarque / Boarding pass. Pasajero RODRIGUEZ/JUAN. Vuelo IB6585 Madrid (MAD) a Bogotá (BOG). Fecha 18 DIC. Puerta K82 Asiento 32A. Embarque 11:35."),
    ("tarjeta-embarque-lisboa", "boarding_pass_MAD_LIS.pdf", "Boarding pass. Flight TP1027 Madrid MAD to Lisboa LIS. Seat 14C. Group 3. Gate closes 20 minutes before departure."),
    ("hotel-lisboa", "reserva_hotel_lisboa.pdf", "Confirmación de reserva. Hotel en el barrio de Alfama, Lisboa. Llegada 3 de mayo, salida 6 de mayo, 3 noches, habitación doble con desayuno. Total 412,50 EUR pagado."),
    ("hotel-tokio", "hotel_tokyo_confirmation.pdf", "Booking confirmation. Hotel near Shinjuku station, Tokyo. Check-in 12 April, check-out 19 April. Twin room, non-smoking. Free cancellation until 5 April."),
    ("itinerario-japon", "itinerario_japon.docx", "Itinerario Japón primavera. Día 1-4 Tokio, día 5 Hakone, día 6-8 Kioto (Fushimi Inari, Arashiyama), día 9 Nara, día 10 Osaka. Japan Rail Pass de 7 días."),
    ("tren-renfe", "billete_tren.pdf", "Billete de tren AVE Madrid Puerta de Atocha a Barcelona Sants. Coche 6 plaza 9A. Salida 08:30 llegada 11:00. Tarifa Básica."),
    ("alquiler-coche", "alquiler_coche_mallorca.pdf", "Contrato de alquiler de vehículo. Recogida aeropuerto de Palma de Mallorca 2 de agosto, devolución 9 de agosto. Categoría compacto, seguro a todo riesgo sin franquicia."),
    ("seguro-viaje", "seguro_viaje.pdf", "Póliza de seguro de viaje internacional. Cobertura de asistencia médica hasta 100.000 EUR, cancelación, pérdida de equipaje. Destino: Colombia. Vigencia diciembre-enero."),
    ("check-in-online", "checkin_ryanair.pdf", "Online check-in completed. Barcelona BCN to London Stansted STN. Priority and 2 cabin bags. Present this pass at security."),
    ("ruta-camino", "camino_santiago.txt", "Etapas del Camino de Santiago desde Sarria: Portomarín, Palas de Rei, Arzúa, O Pedrouzo y Santiago. Unos 115 km. Llevar la credencial para sellar."),
    # Work
    ("contrato-laboral", "contrato_trabajo.pdf", "Contrato de trabajo indefinido a tiempo completo. Empresa contratante y trabajador acuerdan categoría profesional de analista. Periodo de prueba de seis meses. Salario bruto anual 38.000 euros en 14 pagas."),
    ("acta-reunion", "acta_reunion_proyecto.docx", "Acta de la reunión de seguimiento del proyecto. Asistentes: equipo de producto y diseño. Acuerdos: retrasar el lanzamiento dos semanas, revisar el presupuesto y preparar la demo para el cliente."),
    ("propuesta-proyecto", "propuesta_comercial.pdf", "Propuesta comercial para el rediseño de la web corporativa. Alcance, calendario en tres fases, equipo asignado y presupuesto estimado de 24.000 euros más IVA."),
    ("factura-emitida", "factura_cliente_2026_014.pdf", "Factura número 2026-014 emitida a cliente. Concepto: servicios de consultoría de octubre. Base imponible 3.200,00 EUR, IVA 21% 672,00 EUR, retención IRPF 15%."),
    ("cv", "curriculum_vitae.pdf", "Currículum vitae. Experiencia: desarrolladora backend en Python y Go durante seis años. Formación: grado en Ingeniería Informática. Idiomas: español nativo, inglés C1."),
    ("vacaciones", "solicitud_vacaciones.docx", "Solicitud de vacaciones. Solicito disfrutar de los días del 4 al 22 de agosto, ambos inclusive, correspondientes al periodo vacacional de este año."),
    ("informe-trimestral", "q3_report.pdf", "Quarterly business report Q3. Revenue grew 12% quarter over quarter, churn decreased to 2.1%. Headcount: 48. Next quarter priorities: enterprise sales and mobile app."),
    ("nda", "nda_signed.pdf", "Mutual non-disclosure agreement between the parties. Confidential information shall not be disclosed to third parties for a period of three years. Governing law: Spain."),
    ("presentacion", "presentacion_kickoff.pptx", "Kickoff del proyecto. Objetivos, hitos, roles y responsabilidades, riesgos principales y próximos pasos. Diapositiva final: preguntas."),
    ("certificado-retenciones", "certificado_retenciones.pdf", "Certificado de retenciones e ingresos a cuenta del IRPF del ejercicio 2025. Rendimientos del trabajo íntegros 36.500 EUR, retenciones practicadas 6.205 EUR."),
    ("baja-medica", "parte_baja.pdf", "Parte médico de baja por incapacidad temporal. Contingencia: enfermedad común. Duración estimada: 7 días. Próxima revisión médica en una semana."),
    ("onboarding-guide", "employee_handbook.pdf", "Employee handbook. Working hours, remote work policy, expense reimbursement, security training and the code of conduct. Read it during your first week."),
    ("expense-report", "expense_report_berlin.xlsx", "Expense report: Berlin conference. Flights 289 EUR, hotel 3 nights 465 EUR, meals 120 EUR, local transport 34 EUR. Receipts attached."),
    # Health
    ("analitica", "analisis_sangre.pdf", "Resultados de análisis clínicos. Hemograma completo. Glucosa 92 mg/dL, colesterol total 210 mg/dL, LDL 135, HDL 52, triglicéridos 110. Hierro y vitamina D bajos."),
    ("receta-medica", "receta_medica.pdf", "Receta médica electrónica. Medicamento: amoxicilina 500 mg cápsulas. Posología: una cápsula cada 8 horas durante 7 días."),
    ("dentista", "cita_dentista.png", "Clínica dental. Recordatorio de cita: limpieza bucal y revisión el martes 14 a las 17:30. Por favor avise con 24 horas si no puede asistir."),
    ("vacunas", "certificado_vacunacion.pdf", "Certificado internacional de vacunación. Fiebre amarilla, dosis única. Hepatitis A y tétanos actualizados. Válido para viajar a zonas endémicas."),
    ("vacuna-perro", "cartilla_veterinaria_toby.jpg", "Cartilla sanitaria canina. Nombre del animal: Toby, raza beagle. Vacuna antirrábica aplicada el 10/03/2026, próxima dosis en marzo del año siguiente. Desparasitación interna."),
    ("oftalmologo", "graduacion_gafas.pdf", "Informe de optometría. Graduación ojo derecho -1,25 esfera, ojo izquierdo -1,50 esfera -0,50 cilindro. Se recomiendan gafas para conducir y pantallas."),
    ("seguro-salud", "seguro_medico.pdf", "Seguro de salud privado. Cuadro médico, especialistas sin listas de espera, hospitalización y urgencias 24 horas. Copago por consulta 5 euros."),
    # Home
    ("contrato-alquiler", "contrato_arrendamiento.pdf", "Contrato de arrendamiento de vivienda. Renta mensual 950 euros, fianza de un mes, duración de cinco años. El inquilino se hace cargo de los suministros."),
    ("seguro-hogar", "poliza_hogar.pdf", "Póliza de seguro de hogar multirriesgo. Continente 120.000 EUR, contenido 30.000 EUR. Cubre daños por agua, incendio, robo y responsabilidad civil."),
    ("ikea", "ticket_muebles.jpg", "Ticket de compra tienda de muebles. Estantería blanca 49,99, sofá cama 299,00, lámpara de pie 24,99. Total 373,98 EUR. Pago con tarjeta."),
    ("garantia-lavadora", "garantia_lavadora.pdf", "Certificado de garantía. Lavadora de carga frontal 9 kg, 1400 rpm. Garantía de 3 años desde la fecha de compra. Conserve el ticket."),
    ("seguro-coche", "seguro_auto.pdf", "Póliza de seguro de automóvil a terceros ampliado. Vehículo matrícula 1234 KLM. Incluye lunas, robo, incendio y asistencia en viaje desde el kilómetro cero."),
    ("itv", "itv_resultado.pdf", "Inspección técnica de vehículos. Resultado: favorable. Próxima inspección antes de la fecha indicada en la tarjeta. Defectos leves: ninguno."),
    ("comunidad", "acta_comunidad_vecinos.pdf", "Junta ordinaria de la comunidad de propietarios. Se aprueba la derrama para arreglar el ascensor y cambiar el portal. Cuota extraordinaria de 300 euros por vivienda."),
    ("manual-caldera", "manual_caldera.pdf", "Manual de usuario de la caldera de condensación. Ajuste de la temperatura de calefacción y del agua caliente sanitaria. Código de error E10: falta de presión, rellenar el circuito."),
    ("wifi", "nota_router.txt", "Nota: el router está detrás del sofá; para reiniciarlo mantener pulsado el botón de reset 10 segundos. La red de invitados se llama Casa-Invitados."),
    # Bank & taxes
    ("hipoteca", "escritura_hipoteca.pdf", "Escritura de préstamo hipotecario. Capital prestado 180.000 euros a 25 años, tipo fijo 2,9 %. Cuota mensual aproximada 845 euros. Vivienda habitual."),
    ("renta-2025", "declaracion_renta_2025.pdf", "Declaración del Impuesto sobre la Renta de las Personas Físicas, ejercicio 2025. Resultado de la declaración: a devolver 612,40 euros. Modalidad individual."),
    ("ibi", "recibo_ibi.pdf", "Recibo del Impuesto sobre Bienes Inmuebles (IBI) de naturaleza urbana. Valor catastral 98.000 EUR. Importe 412,80 EUR. Domiciliado."),
    ("transferencia", "justificante_transferencia.pdf", "Justificante de transferencia. Ordenante: María García. Beneficiario: Inmobiliaria. Concepto: fianza alquiler piso. Importe 950,00 EUR."),
    ("tarjeta-credito", "extracto_tarjeta.pdf", "Extracto de la tarjeta de crédito. Movimientos: supermercado 86,40, gasolinera 60,00, librería 23,90, restaurante 54,00. Cargo en cuenta el día 5."),
    ("plan-pensiones", "plan_pensiones.pdf", "Plan de pensiones individual. Aportaciones del año 1.500 euros. Rentabilidad acumulada 4,1 %. Derechos consolidados 18.230 euros."),
    # School
    ("boletin-notas", "boletin_notas_lucia.pdf", "Boletín de calificaciones, segundo trimestre. Alumna Lucía. Matemáticas sobresaliente, lengua notable, inglés sobresaliente, educación física bien."),
    ("matricula", "matricula_universidad.pdf", "Resguardo de matrícula. Grado en Psicología, primer curso, 60 créditos. Importe de la matrícula 1.130 euros fraccionado en dos plazos."),
    ("titulo", "titulo_master.pdf", "Título de Máster Universitario en Ciencia de Datos, expedido por la universidad a favor de la interesada, con todos los derechos que a este título otorgan las disposiciones vigentes."),
    ("excursion-colegio", "autorizacion_excursion.pdf", "Autorización para la excursión escolar al museo de ciencias el viernes. Salida 9:00 desde el colegio, regreso 16:30. Traer almuerzo."),
    # Photo metadata / OCR-on-image text (v1 indexes images as text)
    ("foto-playa-concha", "IMG_2041.jpg", "Foto. Álbum Verano 2025. Lugar: Playa de la Concha, San Sebastián. 14 de agosto de 2025, 18:02."),
    ("foto-playa-tayrona", "IMG_3310.jpg", "Foto. Álbum Colombia. Lugar: Parque Tayrona, Cabo San Juan, Magdalena. 27 de diciembre de 2025."),
    ("foto-cumple-playa", "IMG_2107.jpg", "Foto. Álbum Cumpleaños de Lucía. Lugar: Playa de la Malvarrosa, Valencia. Texto detectado: FELIZ CUMPLE LUCÍA 8."),
    ("foto-cumple-casa", "IMG_1502.jpg", "Foto. Álbum Cumpleaños de Pablo. Lugar: Madrid, en casa. Texto detectado en la tarta: 40."),
    ("foto-nieve", "IMG_0811.jpg", "Foto. Álbum Esquí. Lugar: Sierra Nevada, Granada. 2 de febrero de 2026."),
    ("foto-montana", "IMG_0950.jpg", "Foto. Álbum Senderismo. Lugar: Picos de Europa, ruta del Cares. 30 de abril de 2026."),
    ("foto-boda", "DSC_4471.jpg", "Foto. Álbum Boda de Ana y Luis. Lugar: Finca en Toledo. 21 de junio de 2025."),
    ("foto-perro", "IMG_2290.jpg", "Foto. Álbum Toby. Lugar: Parque del Retiro, Madrid. 9 de septiembre de 2025."),
    ("foto-pizarra", "IMG_5512.jpg", "Captura. Texto detectado en una pizarra: Roadmap 2026, Q1 onboarding, Q2 pagos, Q3 app móvil."),
    ("foto-recibo-restaurante", "IMG_5601.jpg", "Foto de un ticket. Texto detectado: Restaurante. 2 menús del día 28,00. Bebidas 6,50. Total 34,50 EUR. Gracias por su visita."),
    ("foto-navidad", "IMG_6620.jpg", "Foto. Álbum Navidad 2025. Lugar: Medellín, Colombia. Alumbrados del río. 24 de diciembre de 2025."),
    ("foto-tokio", "IMG_7004.jpg", "Photo. Album Japan. Place: Shibuya crossing, Tokyo. 13 April 2026, 21:14."),
    ("captura-wifi-aeropuerto", "Screenshot_2026-04-12.png", "Captura de pantalla. Texto detectado: Free Wi-Fi Narita Airport. Connect to the network and accept the terms."),
    ("foto-matricula-coche", "IMG_8120.jpg", "Foto. Texto detectado: 1234 KLM. Parking planta -2, plaza 145."),
    # Misc
    ("lista-compra", "lista_compra.txt", "Lista de la compra: leche, pan, huevos, tomates, aguacates, café, papel higiénico, detergente."),
    ("gimnasio", "contrato_gimnasio.pdf", "Alta en el gimnasio. Cuota mensual 39,90 euros con acceso a sala y clases dirigidas. Permanencia de 12 meses."),
    ("multa", "multa_trafico.pdf", "Notificación de denuncia de tráfico. Exceso de velocidad: 68 km/h en vía limitada a 50 km/h. Importe 100 euros, reducción del 50 % por pronto pago."),
    ("entradas-concierto", "entradas_concierto.pdf", "Entradas para el concierto en el estadio. Sábado 20 de junio, apertura de puertas 19:00. Pista general, dos entradas."),
    ("libro-notas", "notas_libro.md", "Notas de lectura de Cien años de soledad: Macondo, la familia Buendía, el coronel Aureliano y los ciclos que se repiten."),
    ("cursos-ingles", "certificado_ingles.pdf", "Certificate in Advanced English. Overall score C1. Reading, writing, listening and speaking components passed."),
    ("donacion", "certificado_donacion.pdf", "Certificado de donativos a una ONG para la desgravación fiscal. Importe donado en el ejercicio: 180 euros."),
    ("mudanza", "presupuesto_mudanza.pdf", "Presupuesto de mudanza: embalaje, transporte de 25 m³ de Madrid a Valencia, montaje de muebles. Precio cerrado 1.450 euros."),
    ("adopcion-gato", "contrato_adopcion.pdf", "Contrato de adopción responsable de un gato. El adoptante se compromete a esterilizarlo, vacunarlo y no abandonarlo."),
    ("garantia-movil", "factura_movil.pdf", "Factura de compra de teléfono móvil 128 GB, color negro. Precio 699 EUR IVA incluido. Garantía legal de tres años."),
    ("manual-tv", "manual_televisor.pdf", "Quick start guide for the smart TV. Connect the antenna, select the language and scan channels. To reset, hold the power button for 10 seconds."),
    ("receta-cafe", "cafe_frio.txt", "Café frío cold brew: 100 g de café molido grueso por litro de agua fría, reposar 18 horas en la nevera y filtrar."),
    ("viaje-mexico", "notas_viaje_mexico.txt", "Ideas para el viaje a México: Ciudad de México, Oaxaca y la costa de Yucatán. Probar los tacos al pastor y el mole negro."),
    ("receta-sancocho", "sancocho.txt", "Sancocho de gallina. Gallina criolla, yuca, plátano verde, mazorca, papa y cilantro cimarrón. Cocinar a fuego lento dos horas y servir con arroz y aguacate."),
    ("receta-croquetas", "croquetas_jamon.txt", "Croquetas de jamón. Bechamel espesa con jamón serrano picado, enfriar toda la noche, rebozar en huevo y pan rallado y freír en aceite muy caliente."),
    ("receta-curry", "chickpea_curry.md", "Chickpea curry. Onion, garlic, ginger, curry paste, chickpeas, coconut milk and spinach. Simmer 20 minutes and serve with rice."),
    ("tarjeta-embarque-mexico", "boarding_pass_MAD_MEX.pdf", "Tarjeta de embarque. Vuelo AM22 Madrid (MAD) a Ciudad de México (MEX). Asiento 41K. Embarque 23:10. Equipaje facturado 1 pieza."),
    ("hotel-oporto", "reserva_hotel_oporto.pdf", "Confirmación de reserva. Hotel junto al río Duero, Oporto. Dos noches en habitación doble. Total 198,00 EUR. Pago en el alojamiento."),
    ("nda-cliente", "acuerdo_confidencialidad_cliente.pdf", "Acuerdo de confidencialidad con el proveedor de diseño. La información técnica compartida se usará solo para el proyecto y no se divulgará durante dos años."),
    ("annual-report", "annual_report_2025.pdf", "Annual report 2025. Total revenue, operating margin, customer growth by region and the outlook for 2026."),
    ("receta-medica-2", "receta_ibuprofeno.pdf", "Receta médica. Ibuprofeno 600 mg comprimidos, uno cada ocho horas con comida si hay dolor, máximo cinco días."),
    ("foto-cumple-parque", "IMG_2210.jpg", "Foto. Álbum Cumpleaños de Toby. Lugar: Parque del Retiro, Madrid. Texto detectado: 3 AÑOS."),
    ("foto-playa-noche", "IMG_2055.jpg", "Foto. Álbum Verano 2025. Lugar: Paseo marítimo, San Sebastián, de noche. 15 de agosto de 2025."),
    ("seguro-moto", "seguro_moto.pdf", "Póliza de seguro de motocicleta 125 cc a terceros. Incluye casco y asistencia en carretera. Prima anual 210 euros."),
    ("cumple-invitacion", "invitacion_cumple.pdf", "¡Estás invitado al cumpleaños de Pablo! Fiesta sorpresa el sábado a las 20:00 en la terraza. No le digas nada."),
]

PROVIDERS_LUZ = "Compañía Eléctrica del Norte"


def _templated() -> list[tuple[str, str, str]]:
    docs: list[tuple[str, str, str]] = []
    luz = [61.20, 58.75, 49.10, 42.30, 38.90, 55.60, 71.40, 74.85, 52.10, 44.20, 50.70, 66.30]
    for i, month in enumerate(MONTHS_ES):
        docs.append((
            f"luz-2026-{i + 1:02d}",
            f"factura_luz_2026_{i + 1:02d}.pdf",
            f"{PROVIDERS_LUZ}. Factura de electricidad. Periodo de facturación: {month} 2026. Potencia contratada 4,6 kW. "
            f"Consumo {180 + i * 7} kWh. Importe total {luz[i]:.2f} €.",
        ))
    agua = [("enero", "febrero", 31.40), ("marzo", "abril", 29.80), ("mayo", "junio", 35.20), ("julio", "agosto", 44.60), ("septiembre", "octubre", 33.10), ("noviembre", "diciembre", 30.90)]
    for i, (a, b, amount) in enumerate(agua):
        docs.append((
            f"agua-2026-{i + 1}",
            f"recibo_agua_bimestre_{i + 1}.pdf",
            f"Canal de aguas municipal. Recibo de suministro de agua, bimestre {a}-{b} 2026. Consumo {12 + i} m³. Total {amount:.2f} €.",
        ))
    for i, month in enumerate(MONTHS_ES[:6]):
        docs.append((
            f"movil-2026-{i + 1:02d}",
            f"factura_telefono_{i + 1:02d}.pdf",
            f"Operadora de telecomunicaciones. Factura de {month} 2026. Fibra 600 Mb y línea móvil con 50 GB. Total 45,00 € IVA incluido.",
        ))
    for i, month in enumerate(["enero", "febrero", "marzo", "noviembre", "diciembre"]):
        docs.append((
            f"gas-2026-{i + 1}",
            f"factura_gas_{month}.pdf",
            f"Comercializadora de gas natural. Factura de gas del periodo de {month}. Consumo {420 - i * 30} kWh. Término fijo y variable. Importe {58 + i * 4:.2f} €.",
        ))
    for i, month in enumerate(MONTHS_ES):
        docs.append((
            f"nomina-2026-{i + 1:02d}",
            f"nomina_{i + 1:02d}_2026.pdf",
            f"Recibo de salarios. Periodo de liquidación: {month} de 2026. Salario base 2.350,00, complementos 214,00, "
            f"retención IRPF 17 %, Seguridad Social 6,35 %. Líquido a percibir {2120 + (i % 3) * 5},40 €.",
        ))
    for i, month in enumerate(MONTHS_ES):
        docs.append((
            f"extracto-2026-{i + 1:02d}",
            f"extracto_cuenta_{i + 1:02d}.pdf",
            f"Extracto de cuenta corriente, {month} 2026. Saldo inicial, ingresos por nómina, recibos domiciliados de luz, agua y teléfono, "
            f"compras con tarjeta. Saldo final {3100 + i * 87},12 €.",
        ))
    supers = ["Mercadona", "Carrefour", "Lidl", "Dia", "Eroski", "Alcampo", "Consum", "Aldi"]
    for i, name in enumerate(supers):
        docs.append((
            f"ticket-super-{i + 1}",
            f"IMG_ticket_{4000 + i}.jpg",
            f"Foto de un ticket de supermercado. Texto detectado: {name.upper()}. Leche, pan, fruta, yogures, aceite. Total {18 + i * 3.5:.2f} EUR. Tarjeta.",
        ))
    restaurants = ["Taberna del Puerto", "Sushi Kyoto", "Pizzería Napoli", "Asador Castilla", "La Arepería", "Burger 33"]
    for i, name in enumerate(restaurants):
        docs.append((
            f"ticket-rest-{i + 1}",
            f"ticket_restaurante_{i + 1}.jpg",
            f"Ticket. {name}. Mesa {i + 3}. Consumición varia. Total {27 + i * 6:.2f} EUR. IVA incluido.",
        ))
    cities = [("Sevilla", "AVE"), ("Valencia", "Alvia"), ("Bilbao", "Alvia"), ("Málaga", "AVE"), ("Zaragoza", "AVE")]
    for i, (city, kind) in enumerate(cities):
        docs.append((
            f"tren-{i + 1}",
            f"billete_tren_{city.lower()}.pdf",
            f"Billete de tren {kind} Madrid a {city}. Coche {i + 2} plaza {i + 10}B. Tarifa Elige. Presentar el código QR en el acceso.",
        ))
    photos = [
        ("Playa de las Catedrales, Lugo", "Verano 2024"), ("Playa de Bolonia, Cádiz", "Verano 2024"), ("Retiro, Madrid", "Paseos"),
        ("Plaza Mayor, Salamanca", "Escapadas"), ("Sagrada Familia, Barcelona", "Escapadas"), ("Museo del Prado, Madrid", "Paseos"),
        ("Cartagena de Indias, Colombia", "Colombia"), ("Guatapé, Antioquia", "Colombia"), ("Valle de Cocora, Quindío", "Colombia"),
        ("Alhambra, Granada", "Escapadas"), ("Lago de Sanabria, Zamora", "Senderismo"), ("Montserrat, Barcelona", "Senderismo"),
    ]
    for i, (place, album) in enumerate(photos):
        docs.append((
            f"foto-{i + 1:02d}",
            f"IMG_{9000 + i}.jpg",
            f"Foto. Álbum {album}. Lugar: {place}.",
        ))
    english = [
        ("Electricity bill, November 2025. Northern Power Co. Usage 214 kWh. Amount due 63.10 EUR.", "electricity_bill_2025_11.pdf"),
        ("Gym membership renewal reminder. Your annual plan renews on 1 December.", "gym_renewal.eml"),
        ("Parking ticket receipt. Airport long-stay car park, 6 days. 54.00 EUR.", "parking_receipt.pdf"),
        ("Meeting notes: sprint retrospective. What went well, what to improve, action items for the next sprint.", "retro_notes.md"),
        ("Rental car return receipt. Fuel level full. No damage reported. Mileage 412 km.", "car_return.pdf"),
        ("Pharmacy receipt: ibuprofen 400 mg, sunscreen SPF 50, plasters. Total 21.35 EUR.", "pharmacy_receipt.jpg"),
    ]
    for i, (text, title) in enumerate(english):
        docs.append((f"en-misc-{i + 1}", title, text))
    return docs


def documents() -> list[dict[str, str]]:
    rows = [*HAND, *_templated()]
    ids = [r[0] for r in rows]
    assert len(set(ids)) == len(ids), "duplicate document id"
    return [{"id": i, "title": t, "text": x} for i, t, x in rows]


# (id, lang, query, relevant ids). lang: es, en, es->en (Spanish query, English doc), en->es.
QUERIES: list[tuple[str, str, str, list[str]]] = [
    ("q01", "es", "factura de la luz de marzo", ["luz-2026-03"]),
    ("q02", "es", "recibo del agua de julio y agosto", ["agua-2026-4"]),
    ("q03", "es", "mi documento de identidad", ["dni", "nie"]),
    ("q04", "es", "cuándo caduca el pasaporte", ["pasaporte"]),
    ("q05", "es", "carnet de conducir", ["carnet-conducir"]),
    ("q06", "es", "receta de arroz con mariscos", ["receta-paella-marisco", "receta-paella"]),
    ("q07", "es", "sopa fría de tomate", ["receta-gazpacho"]),
    ("q08", "es", "postre con caramelo al horno", ["receta-flan"]),
    ("q09", "es", "receta colombiana con papa y pollo", ["receta-ajiaco", "receta-sancocho"]),
    ("q10", "es", "billete de avión a Bogotá", ["tarjeta-embarque-bogota"]),
    ("q11", "es", "reserva de hotel en Lisboa", ["hotel-lisboa"]),
    ("q12", "es", "qué vamos a visitar en Japón", ["itinerario-japon"]),
    ("q13", "es", "tren a Barcelona", ["tren-renfe"]),
    ("q14", "es", "contrato de trabajo", ["contrato-laboral"]),
    ("q15", "es", "nómina de febrero", ["nomina-2026-02"]),
    ("q16", "es", "análisis de sangre colesterol", ["analitica"]),
    ("q17", "es", "vacuna de la rabia del perro", ["vacuna-perro"]),
    ("q18", "es", "fotos de la playa", ["foto-playa-concha", "foto-playa-tayrona", "foto-cumple-playa", "foto-01", "foto-02"]),
    ("q19", "es", "cumpleaños en la playa", ["foto-cumple-playa"]),
    ("q20", "es", "cuánto pago de alquiler al mes", ["contrato-alquiler"]),
    ("q21", "es", "la declaración de la renta", ["renta-2025"]),
    ("q22", "es", "impuesto del piso del ayuntamiento", ["ibi"]),
    ("q23", "es", "seguro del coche", ["seguro-coche"]),
    ("q24", "es", "la caldera marca error de presión", ["manual-caldera"]),
    ("q25", "es", "notas del colegio de Lucía", ["boletin-notas"]),
    ("q26", "es", "multa por ir rápido", ["multa"]),
    ("q27", "es", "presupuesto para cambiarnos de casa", ["mudanza"]),
    ("q28", "es", "foto de la nieve esquiando", ["foto-nieve"]),
    ("q29", "es", "ticket del supermercado Lidl", ["ticket-super-3"]),
    ("q30", "es", "certificado de vacunas para viajar", ["vacunas"]),
    ("q31", "en", "electricity bill for March", ["luz-2026-03"]),
    ("q32", "en", "passport expiration date", ["pasaporte"]),
    ("q33", "en", "potato omelette recipe", ["receta-tortilla"]),
    ("q34", "en", "flight ticket to Bogota", ["tarjeta-embarque-bogota"]),
    ("q35", "en", "employment contract salary", ["contrato-laboral"]),
    ("q36", "en", "pancake recipe", ["receta-pancakes"]),
    ("q37", "es->en", "informe trimestral de ingresos", ["informe-trimestral"]),
    ("q38", "es->en", "acuerdo de confidencialidad", ["nda", "nda-cliente"]),
    ("q39", "es->en", "receta de pan de plátano", ["receta-banana-bread"]),
    ("q40", "es->en", "hotel en Tokio", ["hotel-tokio"]),
    ("q41", "en->es", "dog vaccination record", ["vacuna-perro"]),
    ("q42", "en", "chocolate dessert", ["receta-brownies"]),
]


def queries() -> list[dict[str, object]]:
    ids = {d["id"] for d in documents()}
    out = []
    for qid, lang, q, rel in QUERIES:
        missing = [r for r in rel if r not in ids]
        assert not missing, (qid, missing)
        out.append({"id": qid, "lang": lang, "q": q, "relevant": rel})
    return out


if __name__ == "__main__":
    print(len(documents()), "documents,", len(queries()), "queries")
