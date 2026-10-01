import json
import pandas as pd
from neo4j import GraphDatabase
import re
import sys
import configparser

# ============================================
# KONFIGURASI
# ============================================
config = configparser.ConfigParser()
config.read('neo4j.ini')

NEO4J_URI      = config['neo4j']['uri']
NEO4J_USER     = config['neo4j']['user']
NEO4J_PASSWORD = config['neo4j']['password']
DATABASE_NAME  = config['neo4j']['database']

# ============================================
# BACA DATA DARI FILE
# ============================================
excel_file = "graph_dataset.xlsx"
df_detail = pd.read_excel(excel_file, sheet_name="detail competency", header=0)
df_header = pd.read_excel(excel_file, sheet_name="header", header=0)

print("Kolom df_header:", df_header.columns.tolist())
print("Kolom df_detail:", df_detail.columns.tolist())

with open("questions.json", "r") as f:
    questions = json.load(f)

with open("knowledge_base_fix.json", "r") as f:
    kb_fix = json.load(f)

concept_map = {}
for unit_data in kb_fix.get('unit', []):
    kode = unit_data.get('kode_unit', '')
    konsep_list = unit_data.get('konsep', [])
    if kode:
        concept_map[kode] = konsep_list

# print(f"📚 Total unit dengan konsep: {len(concept_map)}")
# print(concept_map)

# sys.exit(0)

# ============================================
# KONEKSI NEO4J
# ============================================
class Neo4jConnection:
    def __init__(self, uri, user, password, database):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self):
        self.driver.close()

    def run_query(self, query, parameters=None):
        with self.driver.session(database=self.database) as session:
            result = session.run(query, parameters or {})
            return list(result)

# ============================================
# HELPER: AMBIL NILAI HEADER
# ============================================
def get_header_value(df_header, field_name, default=""):
    try:
        result = df_header[df_header['Field'] == field_name]['Extracted Information']
        if len(result) > 0 and pd.notna(result.values[0]):
            return str(result.values[0]).strip()
        return default
    except Exception as e:
        print(f"⚠️ Gagal ambil {field_name}: {e}")
        return default

# ============================================
# PARSING COMPETENCY UNIT DARI SHEET DETAIL
# ============================================
def parse_competency_units(df):
    """
    Parse setiap CompetencyUnit dari sheet detail.
    - Tidak memparsing isi Extracted Information (kecuali yang perlu split)
    - Mendeteksi 6 unit dengan benar
    - Field baru: CompetencyName, CompetencyWritten
    """
    units = []
    current_unit = None

    for idx, row in df.iterrows():
        # Ambil field dan value, aman terhadap NaN
        field_raw = row.get('Field', None)
        value_raw = row.get('Extracted Information', None)

        # Skip jika field kosong / NaN
        if pd.isna(field_raw):
            continue

        field = str(field_raw).strip()
        if field == '' or field.lower() == 'nan':
            continue

        # Value: bisa NaN
        if pd.isna(value_raw):
            value = ''
        else:
            value = str(value_raw).strip()

        # Deteksi awal unit baru
        if field == 'CompetencyUnit':
            # Simpan unit sebelumnya
            if current_unit is not None:
                units.append(current_unit)
            # Mulai unit baru
            current_unit = {
                'kode': value,           # langsung dari field CompetencyUnit
                'CompetencyName': '',
                'CompetencyWritten': '',
                'UnitDescription': '',
                'ElementCompetency': '',
                'ContextVariable': '',
                'RequiredRegulation': '',
                'ToolsAndEquipment': '',
                'NormAndStandard': '',
                'PrerequisiteCompetency': '',
                'CriticalAspect': '',
                'PerformanceCriterion': '',
                'WorkAttitude': '',
                'KnowledgeAndSkill': ''
            }
        elif current_unit is not None and field in current_unit:
            current_unit[field] = value

    # Simpan unit terakhir
    if current_unit is not None:
        units.append(current_unit)

    return units

competency_units = parse_competency_units(df_detail)

print("\n" + "="*60)
print(f"Total unit ter-parse: {len(competency_units)}")
for i, u in enumerate(competency_units, 1):
    print(f"{i}. Kode: '{u['kode']}' | Name: '{u['CompetencyName'][:60]}'")
print("="*60 + "\n")

# ============================================
# BUAT GRAPH UTAMA
# ============================================
def create_neo4j_graph(conn, units, header_data):
    company_name    = get_header_value(header_data, 'Company')
    role_name       = get_header_value(header_data, 'CompanyRole')
    occupation_name = get_header_value(header_data, 'Occupation')
    area_name       = get_header_value(header_data, 'FunctionArea')
    cert_name       = get_header_value(header_data, 'CertificationScheme')
    stddoc_name     = get_header_value(header_data, 'StandardDocument')

    # 1. Company
    conn.run_query("MERGE (c:Company {name: $name})", {'name': company_name})
    print(f"✅ Company: {company_name}")

    # 2. CompanyRole
    conn.run_query("MERGE (r:CompanyRole {name: $name})", {'name': role_name})
    print(f"✅ CompanyRole: {role_name}")

    # 3. Company - HAS_ROLE -> CompanyRole
    conn.run_query("""
        MATCH (c:Company {name: $company})
        MATCH (r:CompanyRole {name: $role})
        MERGE (c)-[:HAS_ROLE]->(r)
    """, {'company': company_name, 'role': role_name})

    # 4. Occupation
    conn.run_query("MERGE (o:Occupation {name: $name})", {'name': occupation_name})
    print(f"✅ Occupation: {occupation_name}")

    # 5. CompanyRole - MAPS_TO_OCCUPATION -> Occupation
    conn.run_query("""
        MATCH (r:CompanyRole {name: $role})
        MATCH (o:Occupation {name: $occupation})
        MERGE (r)-[:MAPS_TO_OCCUPATION]->(o)
    """, {'role': role_name, 'occupation': occupation_name})

    # 6. FunctionArea
    conn.run_query("MERGE (f:FunctionArea {name: $name})", {'name': area_name})
    print(f"✅ FunctionArea: {area_name}")

    # 7. Occupation - BELONGS_TO_AREA -> FunctionArea
    conn.run_query("""
        MATCH (o:Occupation {name: $occupation})
        MATCH (f:FunctionArea {name: $area})
        MERGE (o)-[:BELONGS_TO_AREA]->(f)
    """, {'occupation': occupation_name, 'area': area_name})

    # 8. StandardDocument
    conn.run_query("MERGE (sd:StandardDocument {name: $name})", {'name': stddoc_name})
    print(f"✅ StandardDocument: {stddoc_name}")

    # 9. Occupation - DEFINED_IN -> StandardDocument
    conn.run_query("""
        MATCH (o:Occupation {name: $occupation})
        MATCH (sd:StandardDocument {name: $stddoc})
        MERGE (o)-[:DEFINED_IN]->(sd)
    """, {'occupation': occupation_name, 'stddoc': stddoc_name})

    # 10. CertificationScheme
    conn.run_query("MERGE (cs:CertificationScheme {name: $name})", {'name': cert_name})
    print(f"✅ CertificationScheme: {cert_name}")

    # 11. Occupation - HAS_CERTIFICATION_SCHEME -> CertificationScheme
    conn.run_query("""
        MATCH (o:Occupation {name: $occupation})
        MATCH (cs:CertificationScheme {name: $cert})
        MERGE (o)-[:HAS_CERTIFICATION_SCHEME]->(cs)
    """, {'occupation': occupation_name, 'cert': cert_name})

    # 12. CertificationScheme - DEFINED_IN -> StandardDocument
    conn.run_query("""
        MATCH (cs:CertificationScheme {name: $cert})
        MATCH (sd:StandardDocument {name: $stddoc})
        MERGE (cs)-[:DEFINED_IN]->(sd)
    """, {'cert': cert_name, 'stddoc': stddoc_name})

    # 13. Meta nodes dari header
    meta_nodes = ['CodeLevel', 'Definition', 'QualificationLevel', 'ScopeOfWork',
                  'Profile', 'Responsibility', 'Authority', 'Requirement', 'CareerPath']
    for node_type in meta_nodes:
        value = get_header_value(header_data, node_type)
        if value:
            conn.run_query(f"MERGE (n:{node_type} {{name: $value}})", {'value': value})
            print(f"✅ {node_type}: {value[:50]}...")

    # ============================================
    # 14. Loop tiap CompetencyUnit
    # ============================================
    for unit in units:
        kode = unit.get('kode', '')
        if not kode:
            continue

        # 14a. CompetencyUnit
        conn.run_query("""
            MERGE (cu:CompetencyUnit {kode: $kode})
        """, {'kode': kode})
        print(f"✅ CompetencyUnit: {kode}")

        # 14b. CertificationScheme - PACKAGES_UNIT -> CompetencyUnit
        conn.run_query("""
            MATCH (cs:CertificationScheme {name: $cert})
            MATCH (cu:CompetencyUnit {kode: $kode})
            MERGE (cs)-[:PACKAGES_UNIT]->(cu)
        """, {'cert': cert_name, 'kode': kode})

        # 14c. CompetencyUnit - DEFINED_IN -> StandardDocument
        conn.run_query("""
            MATCH (cu:CompetencyUnit {kode: $kode})
            MATCH (sd:StandardDocument {name: $stddoc})
            MERGE (cu)-[:DEFINED_IN]->(sd)
        """, {'kode': kode, 'stddoc': stddoc_name})

        # 14d. CompetencyName (node anak)
        if unit.get('CompetencyName'):
            conn.run_query("""
                MATCH (cu:CompetencyUnit {kode: $kode})
                MERGE (cn:CompetencyName {name: $name})
                MERGE (cu)-[:HAS_NAME]->(cn)
            """, {'kode': kode, 'name': unit['CompetencyName']})

        # 14e. CompetencyWritten (node anak)
        if unit.get('CompetencyWritten'):
            conn.run_query("""
                MATCH (cu:CompetencyUnit {kode: $kode})
                MERGE (cw:CompetencyWritten {name: $name})
                MERGE (cu)-[:WRITTEN_AS]->(cw)
            """, {'kode': kode, 'name': unit['CompetencyWritten']})

        # 14f. UnitDescription
        if unit.get('UnitDescription'):
            conn.run_query("""
                MATCH (cu:CompetencyUnit {kode: $kode})
                MERGE (ud:UnitDescription {text: $text})
                MERGE (cu)-[:HAS_DESCRIPTION]->(ud)
            """, {'kode': kode, 'text': unit['UnitDescription']})

        # 14g. ElementCompetency (split per nomor)
        if unit.get('ElementCompetency'):
            # Split berdasarkan "N) " → jadi list elemen
            raw = unit['ElementCompetency']
            # Pisahkan berdasarkan pola angka + ") "
            elements = re.split(r'\s*\d+\)\s*', raw)
            elements = [e.strip().rstrip('.') for e in elements if e.strip()]

            for elem in elements:
                conn.run_query("""
                    MATCH (cu:CompetencyUnit {kode: $kode})
                    MERGE (ec:ElementCompetency {text: $elem})
                    MERGE (cu)-[:HAS_ELEMENT]->(ec)
                """, {'kode': kode, 'elem': elem})

                # PerformanceCriterion turunan ElementCompetency
                if unit.get('PerformanceCriterion'):
                    # Split per "Elemen N – ..." 
                    blocks = re.split(r'(?=Elemen\s+\d+\s*[–\-])', unit['PerformanceCriterion'])
                    for block in blocks:
                        block = block.strip()
                        if not block:
                            continue
                        # Split per "N.N ..."
                        criteria_list = re.split(r'(?=\d+\.\d+\s)', block)
                        for crit in criteria_list:
                            crit = crit.strip()
                            if crit:
                                conn.run_query("""
                                    MATCH (ec:ElementCompetency {text: $elem})
                                    MERGE (pc:PerformanceCriterion {text: $crit})
                                    MERGE (ec)-[:HAS_PERFORMANCE_CRITERION]->(pc)
                                """, {'elem': elem, 'crit': crit})

                # WorkAttitude turunan ElementCompetency
                if unit.get('WorkAttitude'):
                    raw_wa = re.sub(r'^\d+\)\s*', '', unit['WorkAttitude'])
                    for wa in re.split(r',\s*|\d+\)\s*', raw_wa):
                        wa = wa.strip().rstrip('.')
                        if wa:
                            conn.run_query("""
                                MATCH (ec:ElementCompetency {text: $elem})
                                MERGE (wa:WorkAttitude {name: $wa})
                                MERGE (ec)-[:HAS_WORK_ATTITUDE]->(wa)
                            """, {'elem': elem, 'wa': wa})

                # KnowledgeAndSkill turunan ElementCompetency
                if unit.get('KnowledgeAndSkill'):
                    conn.run_query("""
                        MATCH (ec:ElementCompetency {text: $elem})
                        MERGE (ks:KnowledgeAndSkill {text: $text})
                        MERGE (ec)-[:HAS_KNOWLEDGE_AND_SKILL]->(ks)
                    """, {'elem': elem, 'text': unit['KnowledgeAndSkill']})

                    # Concept turunan KnowledgeAndSkill
                    conn.run_query("""
                        MATCH (ec:ElementCompetency {text: $elem})-[:HAS_KNOWLEDGE_AND_SKILL]->(ks:KnowledgeAndSkill)
                        MERGE (c:Concept {name: $concept_name})
                        MERGE (ks)-[:DERIVED_INTO]->(c)
                    """, {'elem': elem, 'concept_name': f"Concept_{kode}"})

                    # 5 anak Concept
                    for child_label, rel_type in [
                        ('LearningMaterial', 'HAS_LEARNING_MATERIAL'),
                        ('Exercise',         'HAS_EXERCISE'),
                        ('StudyCase',        'HAS_STUDY_CASE'),
                        ('PrePostTest',      'HAS_PRE_POST_TEST'),
                        ('Reference',        'HAS_REFERENCE')
                    ]:
                        conn.run_query(f"""
                            MATCH (c:Concept {{name: $concept_name}})
                            MERGE (child:{child_label} {{name: $child_name}})
                            MERGE (c)-[:{rel_type}]->(child)
                        """, {
                            'concept_name': f"Concept_{kode}",
                            'child_name': f"{child_label}_{kode}"
                        })

        # 14h. ContextVariable (ambil teks apa adanya, tapi bisa split per "N)")
        if unit.get('ContextVariable'):
            for ctx in re.split(r'\s*\d+\)\s*', unit['ContextVariable']):
                ctx = ctx.strip().rstrip('.')
                if ctx:
                    conn.run_query("""
                        MATCH (cu:CompetencyUnit {kode: $kode})
                        MERGE (cv:ContextVariable {text: $text})
                        MERGE (cu)-[:HAS_CONTEXT_VARIABLE]->(cv)
                    """, {'kode': kode, 'text': ctx})

        # 14i. RequiredRegulation
        if unit.get('RequiredRegulation') and unit['RequiredRegulation'].strip().lower() != 'tidak ada.':
            for reg in re.split(r'\s*\d+\)\s*', unit['RequiredRegulation']):
                reg = reg.strip().rstrip('.')
                if reg and reg.lower() != 'tidak ada':
                    conn.run_query("""
                        MATCH (cu:CompetencyUnit {kode: $kode})
                        MERGE (rr:RequiredRegulation {name: $text})
                        MERGE (cu)-[:HAS_REQUIRED_REGULATION]->(rr)
                    """, {'kode': kode, 'text': reg})

        # 14j. ToolsAndEquipment (ambil apa adanya sebagai satu node)
        if unit.get('ToolsAndEquipment'):
            conn.run_query("""
                MATCH (cu:CompetencyUnit {kode: $kode})
                MERGE (te:ToolsAndEquipment {text: $text})
                MERGE (cu)-[:HAS_TOOLS_AND_EQUIPMENT]->(te)
            """, {'kode': kode, 'text': unit['ToolsAndEquipment']})

        # 14k. NormAndStandard (ambil apa adanya)
        if unit.get('NormAndStandard'):
            conn.run_query("""
                MATCH (cu:CompetencyUnit {kode: $kode})
                MERGE (ns:NormAndStandard {text: $text})
                MERGE (cu)-[:HAS_NORM_AND_STANDARD]->(ns)
            """, {'kode': kode, 'text': unit['NormAndStandard']})

        # 14l. PrerequisiteCompetency
        if unit.get('PrerequisiteCompetency') and unit['PrerequisiteCompetency'].strip().lower() != 'tidak ada.':
            for prereq in re.split(r'\s*\d+\)\s*', unit['PrerequisiteCompetency']):
                prereq = prereq.strip().rstrip('.')
                if prereq and prereq.lower() != 'tidak ada':
                    conn.run_query("""
                        MATCH (cu:CompetencyUnit {kode: $kode})
                        MERGE (pc:PrerequisiteCompetency {name: $text})
                        MERGE (cu)-[:HAS_PREREQUISITE_COMPETENCY]->(pc)
                    """, {'kode': kode, 'text': prereq})

        # 14m. CriticalAspect (ambil apa adanya)
        if unit.get('CriticalAspect'):
            conn.run_query("""
                MATCH (cu:CompetencyUnit {kode: $kode})
                MERGE (ca:CriticalAspect {text: $text})
                MERGE (cu)-[:HAS_CRITICAL_ASPECT]->(ca)
            """, {'kode': kode, 'text': unit['CriticalAspect']})

        print(f"✅ Semua atribut untuk {kode} selesai")

    print("\n" + "="*50)
    print("✅ SEMUA COMPETENCY UNIT SELESAI DIBUAT")
    print("="*50 + "\n")

# ============================================
# BUAT EVALUATION QUESTION DARI JSON
# ============================================
def create_evaluation_questions(conn, questions):
    total = len(questions)
    print(f"Membuat {total} soal EvaluationQuestion...")

    for i, q in enumerate(questions, 1):
        unit_kode       = q.get('unit', '')
        question_text   = q.get('question', '')
        bloom_level     = q.get('bloom_level', '')
        correct_answer  = q.get('correct_answer', '')
        options         = q.get('options', [])

        # Cek apakah CompetencyUnit ada
        result = conn.run_query("""
            MATCH (cu:CompetencyUnit {kode: $kode})
            RETURN cu
        """, {'kode': unit_kode})

        if not result:
            print(f"⚠️ Unit {unit_kode} tidak ditemukan, lewati soal {i}")
            continue

        # Buat EvaluationQuestion
        conn.run_query("""
            CREATE (eq:EvaluationQuestion {
                soal: $question,
                bloom_level: $bloom_level,
                jawaban: $jawaban,
                source: 'adaptive_question'
            })
        """, {
            'question': question_text,
            'bloom_level': bloom_level,
            'jawaban': correct_answer
        })

        # ASSESSED_BY: dari SETIAP PerformanceCriterion unit ini ke EvaluationQuestion
        conn.run_query("""
            MATCH (cu:CompetencyUnit {kode: $kode})
                  -[:HAS_ELEMENT]->(:ElementCompetency)
                  -[:HAS_PERFORMANCE_CRITERION]->(pc:PerformanceCriterion)
            MATCH (eq:EvaluationQuestion {soal: $question})
            MERGE (pc)-[:ASSESSED_BY]->(eq)
        """, {'kode': unit_kode, 'question': question_text})

        # AnswerOption
        for opt in options:
            conn.run_query("""
                MATCH (eq:EvaluationQuestion {soal: $question})
                MERGE (ao:AnswerOption {text: $text})
                MERGE (eq)-[:HAS_ANSWER_OPTION]->(ao)
            """, {'question': question_text, 'text': opt})

        # CorrectAnswer
        conn.run_query("""
            MATCH (eq:EvaluationQuestion {soal: $question})
            MERGE (ca:CorrectAnswer {text: $jawaban})
            MERGE (eq)-[:HAS_CORRECT_ANSWER]->(ca)
        """, {'question': question_text, 'jawaban': correct_answer})

        # DifficultyLevel
        conn.run_query("""
            MATCH (eq:EvaluationQuestion {soal: $question})
            MERGE (dl:DifficultyLevel {name: $bloom_level})
            MERGE (eq)-[:HAS_DIFFICULTY_LEVEL]->(dl)
        """, {'question': question_text, 'bloom_level': bloom_level})

        if i % 10 == 0:
            print(f"  ✅ {i}/{total} soal selesai")

    print(f"✅ Semua {total} soal EvaluationQuestion selesai dibuat")

# =======================================================
# ISI LEARNING MATERIAL DARI CONCEPT PER UNIT COMPETENCY
# =======================================================
def populate_learning_materials(conn, concept_map):
    """
    Menambahkan node LearningMaterial dari knowledge_base_fix.json
    ke setiap Concept yang sudah ada (kerangka kosong).
    - Concept TIDAK diubah
    - Hanya menambah LearningMaterial + relasi HAS_LEARNING_MATERIAL
    """
    total_konsep = 0
    total_unit = 0

    print("\n" + "="*60)
    print("📚 MENGISI LEARNING MATERIAL DARI knowledge_base_fix.json")
    print("="*60)

    for kode, konsep_list in concept_map.items():
        # Cari Concept yang sudah ada untuk unit ini
        result = conn.run_query("""
            MATCH (cu:CompetencyUnit {kode: $kode})
                  -[:HAS_ELEMENT]->(:ElementCompetency)
                  -[:HAS_KNOWLEDGE_AND_SKILL]->(ks:KnowledgeAndSkill)
                  -[:DERIVED_INTO]->(c:Concept)
            RETURN DISTINCT c.name AS concept_name
        """, {'kode': kode})

        if not result:
            print(f"⚠️ {kode}: Concept tidak ditemukan, lewati")
            continue

        concept_names = [r['concept_name'] for r in result if r['concept_name']]
        if not concept_names:
            print(f"⚠️ {kode}: Concept kosong, lewati")
            continue

        # Untuk setiap konsep di JSON, buat LearningMaterial
        # dan hubungkan ke SEMUA Concept yang ada di unit ini
        for idx, konsep_text in enumerate(konsep_list, 1):
            konsep_text = str(konsep_text).strip()
            if not konsep_text:
                continue

            for concept_name in concept_names:
                lm_id = f"LM_{kode}_{idx}"

                conn.run_query("""
                    MATCH (c:Concept {name: $concept_name})
                    MERGE (lm:LearningMaterial {lm_id: $lm_id})
                    SET lm.text = $text,
                        lm.kode_unit = $kode,
                        lm.urutan = $urutan
                    MERGE (c)-[:HAS_LEARNING_MATERIAL]->(lm)
                """, {
                    'concept_name': concept_name,
                    'lm_id': lm_id,
                    'text': konsep_text,
                    'kode': kode,
                    'urutan': idx
                })

            total_konsep += 1

        total_unit += 1
        print(f"   ✅ {kode}: {len(konsep_list)} LearningMaterial ditambahkan")

    print("="*60)
    print(f"✅ TOTAL: {total_konsep} LearningMaterial di {total_unit} unit")
    print("="*60 + "\n")

# ============================================
# RELASI TAMBAHAN
# ============================================
def connect_additional_relationships(conn, units):
    print("✅ Relasi tambahan sudah ditangani di create_neo4j_graph")

# ============================================
# EKSEKUSI UTAMA
# ============================================
def main():
    conn = Neo4jConnection(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, DATABASE_NAME)

    print("="*60)
    print("🚀 MEMBANGUN KNOWLEDGE BASE GRAPH DI NEO4J")
    print("="*60)
    print(f"Database: {DATABASE_NAME}")
    print(f"Competency Units: {len(competency_units)}")
    print(f"Soal: {len(questions)}")
    print("="*60 + "\n")

    try:
        create_neo4j_graph(conn, competency_units, df_header)
        create_evaluation_questions(conn, questions)
        connect_additional_relationships(conn, competency_units)
        populate_learning_materials(conn, concept_map)

        print("\n" + "="*60)
        print("✅ SEMUA DATA BERHASIL DIIMPOR KE NEO4J!")
        print("="*60)

        stats = conn.run_query("""
            MATCH (n)
            RETURN labels(n)[0] AS Label, count(n) AS Count
            ORDER BY Count DESC
        """)
        print("\n📊 STATISTIK NODE:")
        for record in stats:
            print(f"  - {record['Label']}: {record['Count']}")

    except Exception as e:
        print(f"❌ ERROR: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()