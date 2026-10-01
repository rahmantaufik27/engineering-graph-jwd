# ============================================
# GENERATE MATERI BARU DENGAN LLM LOKAL
# ============================================
import ollama  # atau: from openai import OpenAI
from main_fix import Neo4jConnection
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

LLM_MODEL = "qwen2.5:1.5b"  # ganti sesuai model lokal Anda
LLM_HOST  = "http://localhost:11434"  # default Ollama


def get_existing_materials(conn, kode_unit):
    """Ambil semua LearningMaterial yang sudah ada untuk 1 unit"""
    result = conn.run_query("""
        MATCH (cu:CompetencyUnit {kode: $kode})
              -[:HAS_ELEMENT]->(:ElementCompetency)
              -[:HAS_KNOWLEDGE_AND_SKILL]->(:KnowledgeAndSkill)
              -[:DERIVED_INTO]->(:Concept)
              -[:HAS_LEARNING_MATERIAL]->(lm:LearningMaterial)
        RETURN lm.text AS text, lm.urutan AS urutan
        ORDER BY lm.urutan
    """, {'kode': kode_unit})
    return [r['text'] for r in result if r['text']]


def generate_new_material(kode_unit, existing_materials):
    """
    Generate materi baru berdasarkan contoh materi yang ada.
    Output sementara hanya di-print.
    """
    # if not existing_materials:
    #     print(f"Tidak ada materi lama untuk unit {kode_unit}")
    #     return None

    # # Gabung contoh materi (batasi biar tidak overflow context)
    # contoh = "\n\n---\n\n".join(existing_materials[:3])
    MAX_CHARS = 6000  # aman untuk model 8K context
    contoh = ""
    for m in existing_materials:
        if len(contoh) + len(m) > MAX_CHARS:
            break
        contoh += "\n\n---\n\n" + m

    # # Topik default: lanjutan / pendalaman
    # if not topik_baru:
    #     topik_baru = "advanced and practical application of the topics above"

#     prompt = f"""You are a curriculum writer for a Junior Web Developer competency unit.
        # Below are EXISTING learning materials for unit {kode_unit}:

        # {contoh}

        # TASK:
        # Write ONE new learning material in Bahasa Indonesia (3-5 paragraphs) 
        # that continues or deepens the topic above. Focus on: {topik_baru}.

        # Requirements:
        # - Use a clear, instructional tone
        # - Include concrete examples relevant to web development
        # - Do NOT repeat the existing materials verbatim
        # - Output ONLY the new material text, no preamble
    # """

    prompt = f"""You are a curriculum writer for the competency unit:
        UNIT CODE: {kode_unit}

        EXISTING MATERIALS (as reference):
        {contoh}

        TASK:
        1. Identify the main topic(s) covered in the existing materials above.
        2. Write ONE NEW learning material in Bahasa Indonesia (3-5 paragraphs) 
        that DEEPENS or EXTENDS those topics with:
        - Practical/real-world examples
        - Case studies relevant to Junior Web Developer
        - More advanced aspects not yet covered

        Output format:
        TOPIC: <topik yang Anda identifikasi>
        ---
        MATERIAL:
        <materi baru>
    """

    try:
        response = ollama.chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.7}
        )
        materi_baru = response['message']['content'].strip()
    except Exception as e:
        print(f"❌ LLM error: {e}")
        return None

    # Tampilkan hasil (sementara: print saja)
    print("\n" + "="*60)
    print(f"📝 MATERI BARU untuk {kode_unit}")
    print("="*60)
    print(materi_baru)
    print("="*60 + "\n")

    return materi_baru


def generate_material_for_all_units(conn):
    """Loop semua unit, generate 1 materi baru per unit"""
    units = conn.run_query("""
        MATCH (cu:CompetencyUnit)
        RETURN cu.kode AS kode
        ORDER BY cu.kode
    """)

    for u in units:
        kode = u['kode']
        existing = get_existing_materials(conn, kode)
        if not existing:
            print(f"⚠️ {kode}: tidak ada materi, skip")
            continue
        generate_new_material(kode, existing)

def generate_material_for_specific_units(conn, list_kode_unit, topik_baru=None):
    """
    Generate materi baru hanya untuk unit yang ada di list_kode_unit.
    """
    for kode in list_kode_unit:
        existing = get_existing_materials(conn, kode)
        if not existing:
            print(f"⚠️ {kode}: tidak ada materi, skip")
            continue
        generate_new_material(kode, existing)

# EKSEKUSI UTAMA
# ============================================
def main():
    conn = Neo4jConnection(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, DATABASE_NAME)
    # generate_material_for_all_units(conn)
    generate_material_for_specific_units(conn, [
        "J.620100.005.02",
        "J.620100.010.01"
    ])

if __name__ == "__main__":
    main()