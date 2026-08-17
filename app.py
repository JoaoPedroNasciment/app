import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
import calendar
import uuid
import pandas as pd
import plotly.express as px
import time

# ============================================================
# CONFIGURAÇÃO
# ============================================================
st.set_page_config(
    page_title="Financeiro",
    page_icon="💜",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS estilo Nubank (limpo, moderno e roxo)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp {
        background-color: #f7f7f7;
    }

    /* Cards */
    .card {
        background: white;
        padding: 1.4rem;
        border-radius: 16px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }

    .metric-card {
        background: white;
        padding: 1.2rem 1rem;
        border-radius: 16px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        text-align: center;
    }

    .metric-card h3 {
        font-size: 0.85rem;
        color: #666;
        margin-bottom: 0.3rem;
        font-weight: 500;
    }

    .metric-card p {
        font-size: 1.4rem;
        font-weight: 700;
        margin: 0;
        color: #1a1a1a;
    }

    .positive { color: #00a86b !important; }
    .negative { color: #e74c3c !important; }

    /* Botões */
    .stButton > button {
        border-radius: 12px;
        font-weight: 600;
        height: 2.8rem;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #820AD1;
    }

    section[data-testid="stSidebar"] * {
        color: white !important;
    }

    section[data-testid="stSidebar"] .stRadio label {
        color: white !important;
    }

    /* Títulos */
    h1, h2, h3 {
        color: #1a1a1a !important;
    }

    /* Dataframe */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# BANCO DE DADOS
# ============================================================
def get_connection():
    try:
        url = st.secrets["DATABASE_URL"]
    except:
        url = "postgresql://neondb_owner:npg_X0vkOIP4Rdig@ep-wandering-feather-axo8n32f-pooler.c-4.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def run_query(query, params=None, fetch=True):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(query, params or ())
        if fetch:
            result = cur.fetchall()
            conn.commit()
            return result
        else:
            conn.commit()
            return True
    except Exception as e:
        conn.rollback()
        st.error(f"Erro no banco: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def format_brl(valor):
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"


def add_months(d, months):
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("## 💜 Financeiro")
    st.markdown("---")
    menu = st.radio(
        "Navegação",
        ["Visão do Mês", "Adicionar", "Categorias", "Todas Transações", "Totais"],
        label_visibility="collapsed"
    )
    st.markdown("---")
    
    # Atualização automática
    auto_refresh = st.checkbox("Atualizar automaticamente (30s)", value=False)
    if st.button("🔄 Atualizar agora", use_container_width=True):
        st.rerun()

    st.markdown("")
    st.caption("Dados em tempo real no banco Neon")


# Auto refresh
if auto_refresh:
    time.sleep(30)
    st.rerun()


# ============================================================
# 1. VISÃO DO MÊS
# ============================================================
if menu == "Visão do Mês":
    st.markdown("## Visão do Mês")

    col_date, col_btn = st.columns([3, 1])
    with col_date:
        mes_selecionado = st.date_input("Escolha o mês", value=date.today(), format="DD/MM/YYYY")
    with col_btn:
        st.write("")
        st.write("")
        if st.button("🔄", help="Atualizar dados"):
            st.rerun()

    ano = mes_selecionado.year
    mes = mes_selecionado.month
    nome_mes = mes_selecionado.strftime("%B / %Y").capitalize()

    # Dados
    resumo = run_query("""
        SELECT type, COALESCE(SUM(amount), 0) as total
        FROM transactions
        WHERE user_id = 1
          AND EXTRACT(YEAR FROM date) = %s
          AND EXTRACT(MONTH FROM date) = %s
        GROUP BY type
    """, (ano, mes)) or []

    summary = {"Despesa": 0.0, "Receita": 0.0}
    for r in resumo:
        summary[r["type"]] = float(r["total"])

    abatidas = run_query("""
        SELECT COALESCE(SUM(amount), 0) as total
        FROM transactions
        WHERE user_id = 1 AND type = 'Despesa'
          AND EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s
          AND deducted_from_balance = TRUE
    """, (ano, mes))
    deducted = float(abatidas[0]["total"]) if abatidas else 0.0

    nao_pagas = run_query("""
        SELECT COALESCE(SUM(amount), 0) as total, COUNT(*) as qtd
        FROM transactions
        WHERE user_id = 1 AND type = 'Despesa'
          AND EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s
          AND status = 'Não Pago'
    """, (ano, mes))
    unpaid_total = float(nao_pagas[0]["total"]) if nao_pagas else 0.0
    unpaid_count = nao_pagas[0]["qtd"] if nao_pagas else 0

    saldo = summary["Receita"] - deducted

    # Cards de resumo
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Receitas</h3>
            <p class="positive">{format_brl(summary['Receita'])}</p>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Despesas Abatidas</h3>
            <p class="negative">{format_brl(deducted)}</p>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        cor = "positive" if saldo >= 0 else "negative"
        st.markdown(f"""
        <div class="metric-card">
            <h3>Saldo</h3>
            <p class="{cor}">{format_brl(saldo)}</p>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Não Pagas</h3>
            <p class="negative">{format_brl(unpaid_total)}</p>
        </div>
        """, unsafe_allow_html=True)

    if unpaid_count > 0:
        st.warning(f"⚠ {unpaid_count} transação(ões) ainda não pagas neste mês")
    else:
        st.success("✓ Todas as transações deste mês estão pagas")

    st.markdown(f"### Transações de {nome_mes}")

    transacoes = run_query("""
        SELECT t.id, t.type, COALESCE(c.name, 'Sem Categoria') as categoria,
               t.amount, t.date, t.description, t.status, t.paid_date,
               t.installments, t.installment_number, t.deducted_from_balance
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = 1
          AND EXTRACT(YEAR FROM t.date) = %s
          AND EXTRACT(MONTH FROM t.date) = %s
        ORDER BY t.date, t.installment_number
    """, (ano, mes))

    if transacoes:
        df = pd.DataFrame(transacoes)
        df["Valor"] = df["amount"].apply(lambda x: format_brl(x))
        df["Data"] = pd.to_datetime(df["date"]).dt.strftime("%d/%m/%Y")
        df["Parcela"] = df.apply(
            lambda x: f"{int(x['installment_number'])}/{int(x['installments'])}" 
            if x["installments"] and x["installments"] > 0 else "-", axis=1
        )
        df["Abatido"] = df["deducted_from_balance"].apply(lambda x: "Sim" if x else "Não")

        st.dataframe(
            df[["id", "type", "categoria", "Valor", "Data", "description", "status", "Parcela", "Abatido"]].rename(columns={
                "id": "ID",
                "type": "Tipo",
                "categoria": "Categoria",
                "description": "Descrição",
                "status": "Status"
            }),
            use_container_width=True,
            hide_index=True
        )

        st.markdown("### Ações Rápidas")
        col1, col2 = st.columns(2)

        with col1:
            with st.expander("Marcar como Pago", expanded=False):
                id_marcar = st.number_input("ID da transação", min_value=1, step=1, key="id_pago")
                opcao = st.radio("Como deseja marcar?", 
                                 ["Apenas marcar como Pago", "Marcar e Abater do Saldo"],
                                 key="opcao_pago")
                if st.button("Confirmar Pagamento", use_container_width=True):
                    deduct = opcao == "Marcar e Abater do Saldo"
                    run_query("""
                        UPDATE transactions
                        SET status = 'Pago', paid_date = %s, deducted_from_balance = %s
                        WHERE id = %s AND type = 'Despesa'
                    """, (date.today(), deduct, id_marcar), fetch=False)
                    st.success("Atualizado com sucesso!")
                    time.sleep(0.8)
                    st.rerun()

        with col2:
            with st.expander("Excluir Transação", expanded=False):
                id_excluir = st.number_input("ID da transação", min_value=1, step=1, key="id_del")
                if st.button("Excluir", type="primary", use_container_width=True):
                    info = run_query("SELECT parent_id, installments FROM transactions WHERE id = %s", (id_excluir,))
                    if info and info[0]["parent_id"] and info[0]["installments"] and info[0]["installments"] > 0:
                        run_query("DELETE FROM transactions WHERE parent_id = %s", (info[0]["parent_id"],), fetch=False)
                    else:
                        run_query("DELETE FROM transactions WHERE id = %s", (id_excluir,), fetch=False)
                    st.success("Excluído!")
                    time.sleep(0.8)
                    st.rerun()

        # Gráficos
        st.markdown("### Gráficos")
        g1, g2 = st.columns(2)

        with g1:
            fig1 = px.bar(
                x=["Receitas", "Despesas Abatidas"],
                y=[summary["Receita"], deducted],
                color=["Receitas", "Despesas Abatidas"],
                color_discrete_map={"Receitas": "#00a86b", "Despesas Abatidas": "#e74c3c"},
                title="Resumo do Mês"
            )
            fig1.update_layout(showlegend=False, plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig1, use_container_width=True)

        with g2:
            cat_data = run_query("""
                SELECT COALESCE(c.name, 'Sem Categoria') as nome, SUM(t.amount) as total
                FROM transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.user_id = 1 AND t.type = 'Despesa'
                  AND EXTRACT(YEAR FROM t.date) = %s AND EXTRACT(MONTH FROM t.date) = %s
                GROUP BY c.name ORDER BY total DESC
            """, (ano, mes))
            if cat_data:
                df_cat = pd.DataFrame(cat_data)
                df_cat["total"] = df_cat["total"].astype(float)
                fig2 = px.bar(df_cat, x="nome", y="total", title="Despesas por Categoria",
                              color_discrete_sequence=["#820AD1"])
                fig2.update_layout(plot_bgcolor="white", paper_bgcolor="white")
                st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Nenhuma transação neste mês.")


# ============================================================
# 2. ADICIONAR TRANSAÇÃO
# ============================================================
elif menu == "Adicionar":
    st.markdown("## Adicionar Transação")

    categorias = run_query("SELECT id, name, type FROM categories ORDER BY type, name") or []
    cat_options = {f"{c['name']} ({c['type']})": c["id"] for c in categorias}

    with st.form("form_nova_transacao", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        with col2:
            parcelas = st.selectbox("Parcelas", [0, 2, 3, 4, 5, 6, 12], 
                                    help="0 = pagamento único")

        categoria = st.selectbox("Categoria", list(cat_options.keys()) if cat_options else ["Nenhuma"])
        valor = st.number_input("Valor (R$)", min_value=0.01, step=0.01, format="%.2f")
        data_trans = st.date_input("Data", value=date.today())
        descricao = st.text_input("Descrição (opcional)")

        enviado = st.form_submit_button("Cadastrar Transação", use_container_width=True)

        if enviado:
            if not cat_options:
                st.error("Crie pelo menos uma categoria antes.")
            else:
                cat_id = cat_options[categoria]
                try:
                    if parcelas > 1 and tipo == "Despesa":
                        amount_per = round(valor / parcelas, 2)
                        last_amount = round(valor - amount_per * (parcelas - 1), 2)
                        parent_id = str(uuid.uuid4())

                        for i in range(parcelas):
                            inst_date = add_months(data_trans, i)
                            amount = last_amount if i == parcelas - 1 else amount_per
                            desc = f"{descricao or 'Sem descrição'} (Parcela {i+1}/{parcelas})"

                            run_query("""
                                INSERT INTO transactions
                                (user_id, type, category_id, amount, date, description,
                                 status, installments, installment_number, parent_id, deducted_from_balance)
                                VALUES (1, %s, %s, %s, %s, %s, 'Não Pago', %s, %s, %s, FALSE)
                            """, (tipo, cat_id, amount, inst_date, desc, parcelas, i+1, parent_id), fetch=False)
                    else:
                        run_query("""
                            INSERT INTO transactions
                            (user_id, type, category_id, amount, date, description, status, deducted_from_balance)
                            VALUES (1, %s, %s, %s, %s, %s, 'Não Pago', FALSE)
                        """, (tipo, cat_id, valor, data_trans, descricao or "Sem descrição"), fetch=False)

                    st.success("Transação cadastrada com sucesso!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao cadastrar: {e}")


# ============================================================
# 3. CATEGORIAS
# ============================================================
elif menu == "Categorias":
    st.markdown("## Categorias")

    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.markdown("#### Nova Categoria")
        with st.form("form_cat"):
            nome = st.text_input("Nome da categoria")
            tipo_cat = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
            if st.form_submit_button("Adicionar", use_container_width=True):
                if nome.strip():
                    run_query("""
                        INSERT INTO categories (name, type)
                        VALUES (%s, %s)
                        ON CONFLICT (name, type) DO NOTHING
                    """, (nome.strip(), tipo_cat), fetch=False)
                    st.success("Categoria criada!")
                    time.sleep(0.8)
                    st.rerun()
                else:
                    st.warning("Digite um nome")

    with col2:
        st.markdown("#### Categorias existentes")
        cats = run_query("SELECT id, name, type FROM categories ORDER BY type, name") or []
        if cats:
            df_cats = pd.DataFrame(cats)
            st.dataframe(df_cats, use_container_width=True, hide_index=True)

            id_del = st.number_input("ID para excluir", min_value=1, step=1, key="del_cat")
            if st.button("Excluir categoria", use_container_width=True):
                uso = run_query("SELECT COUNT(*) as total FROM transactions WHERE category_id = %s", (id_del,))
                if uso and uso[0]["total"] > 0:
                    st.error("Essa categoria está em uso e não pode ser excluída.")
                else:
                    run_query("DELETE FROM categories WHERE id = %s", (id_del,), fetch=False)
                    st.success("Categoria excluída!")
                    time.sleep(0.8)
                    st.rerun()


# ============================================================
# 4. TODAS AS TRANSAÇÕES
# ============================================================
elif menu == "Todas Transações":
    st.markdown("## Todas as Transações")

    todas = run_query("""
        SELECT t.id, t.type, COALESCE(c.name, 'Sem Categoria') as categoria,
               t.amount, t.date, t.description, t.status,
               CASE WHEN t.installments > 0 THEN t.installment_number || '/' || t.installments ELSE '-' END as parcela,
               CASE WHEN t.deducted_from_balance THEN 'Sim' ELSE 'Não' END as abatido
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = 1
        ORDER BY t.date DESC
    """) or []

    if todas:
        df = pd.DataFrame(todas)
        df["Valor"] = df["amount"].apply(format_brl)
        df["Data"] = pd.to_datetime(df["date"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            df[["id", "type", "categoria", "Valor", "Data", "description", "status", "parcela", "abatido"]].rename(columns={
                "id": "ID", "type": "Tipo", "categoria": "Categoria",
                "description": "Descrição", "status": "Status",
                "parcela": "Parcela", "abatido": "Abatido"
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Nenhuma transação cadastrada ainda.")


# ============================================================
# 5. TOTAIS
# ============================================================
elif menu == "Totais":
    st.markdown("## Totais Gerais")

    total_nao_pago = run_query("""
        SELECT COALESCE(SUM(amount), 0) as total
        FROM transactions
        WHERE user_id = 1 AND type = 'Despesa' AND status = 'Não Pago'
    """)
    total_unpaid = float(total_nao_pago[0]["total"]) if total_nao_pago else 0.0

    ano_atual = date.today().year
    receitas_ano = run_query("""
        SELECT COALESCE(SUM(amount), 0) as total
        FROM transactions
        WHERE user_id = 1 AND type = 'Receita' AND EXTRACT(YEAR FROM date) = %s
    """, (ano_atual,))
    total_receitas = float(receitas_ano[0]["total"]) if receitas_ano else 0.0

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Total Não Pagos (Geral)</h3>
            <p class="negative">{format_brl(total_unpaid)}</p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Receitas de {ano_atual}</h3>
            <p class="positive">{format_brl(total_receitas)}</p>
        </div>
        """, unsafe_allow_html=True)