import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, timedelta
import calendar
import uuid
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ============================================================
# CONFIGURAÇÃO DO BANCO
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
            return None
    except Exception as e:
        conn.rollback()
        st.error(f"Erro no banco: {e}")
        return None
    finally:
        cur.close()
        conn.close()

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================
def fmt_brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def add_months(d, months):
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def get_categories():
    return run_query("SELECT id, name, type FROM categories ORDER BY type, name") or []

def get_transaction(tx_id):
    res = run_query("""
        SELECT id, type, category_id, amount, date, description, status, paid_date,
               installments, installment_number, parent_id, deducted_from_balance
        FROM transactions WHERE id = %s
    """, (tx_id,))
    return res[0] if res else None

# ============================================================
# INICIALIZAÇÃO SESSION STATE
# ============================================================
if "view_month" not in st.session_state:
    st.session_state.view_month = date.today()
if "editing_id" not in st.session_state:
    st.session_state.editing_id = None

# ============================================================
# PÁGINA PRINCIPAL
# ============================================================
st.set_page_config(page_title="Financeiro", page_icon="💰", layout="wide")
st.title("💰 Gerenciador Financeiro")

# Sidebar com navegação principal (abas)
menu = st.sidebar.radio(
    "Navegação",
    ["📊 Visão Geral", "➕ Nova Transação", "🏷️ Categorias", "📋 Todas", "📈 Totais"],
    index=0
)

# ============================================================
# 1. VISÃO GERAL (aba principal)
# ============================================================
if menu == "📊 Visão Geral":
    st.header("📅 Visão Geral")

    # Controles de mês compactos
    col_mes1, col_mes2, col_mes3 = st.columns([1, 4, 1])
    with col_mes1:
        if st.button("◀", use_container_width=True):
            st.session_state.view_month = st.session_state.view_month - timedelta(days=30)
            st.rerun()
    with col_mes2:
        novo_mes = st.date_input(
            "Mês/Ano",
            value=st.session_state.view_month,
            format="MM/YYYY",
            label_visibility="collapsed"
        )
        st.session_state.view_month = novo_mes.replace(day=1)
    with col_mes3:
        if st.button("▶", use_container_width=True):
            st.session_state.view_month = st.session_state.view_month + timedelta(days=30)
            st.rerun()

    ano = st.session_state.view_month.year
    mes = st.session_state.view_month.month
    nome_mes = st.session_state.view_month.strftime("%B/%Y").capitalize()

    # ====== RESUMO EM CARDS ======
    resumo = run_query("""
        SELECT type, COALESCE(SUM(amount), 0) as total
        FROM transactions
        WHERE user_id = 1 AND EXTRACT(YEAR FROM date)=%s AND EXTRACT(MONTH FROM date)=%s
        GROUP BY type
    """, (ano, mes))
    total_rec = sum(r["total"] for r in resumo if r["type"]=="Receita")
    total_desp_bruto = sum(r["total"] for r in resumo if r["type"]=="Despesa")

    abatidas = run_query("""
        SELECT COALESCE(SUM(amount), 0) as total
        FROM transactions
        WHERE user_id=1 AND type='Despesa' AND deducted_from_balance=TRUE
          AND EXTRACT(YEAR FROM date)=%s AND EXTRACT(MONTH FROM date)=%s
    """, (ano, mes))
    desp_abatidas = abatidas[0]["total"] if abatidas else 0.0

    nao_pagas = run_query("""
        SELECT COALESCE(SUM(amount), 0) as total, COUNT(*) as qtd
        FROM transactions
        WHERE user_id=1 AND type='Despesa' AND status='Não Pago'
          AND EXTRACT(YEAR FROM date)=%s AND EXTRACT(MONTH FROM date)=%s
    """, (ano, mes))
    total_naopago = nao_pagas[0]["total"] if nao_pagas else 0.0
    qtd_naopago = nao_pagas[0]["qtd"] if nao_pagas else 0

    saldo = total_rec - desp_abatidas

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Receitas", fmt_brl(total_rec))
    c2.metric("Despesas Abatidas", fmt_brl(desp_abatidas))
    c3.metric("Saldo", fmt_brl(saldo), delta_color="normal" if saldo>=0 else "inverse")
    c4.metric("Não Pagas", fmt_brl(total_naopago), help=f"{qtd_naopago} transações")

    if qtd_naopago > 0:
        st.warning(f"⚠ {qtd_naopago} transação(ões) não paga(s) neste mês")
    else:
        st.success("✓ Todas as transações pagas")

    # ====== LISTA DE TRANSAÇÕES COM AÇÕES ======
    st.subheader(f"Transações - {nome_mes}")

    # Buscar transações
    transacoes = run_query("""
        SELECT t.id, t.type, COALESCE(c.name, 'Sem Categoria') as categoria,
               t.amount, t.date, t.description, t.status, t.paid_date,
               t.installments, t.installment_number, t.deducted_from_balance
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = 1
          AND EXTRACT(YEAR FROM t.date)=%s AND EXTRACT(MONTH FROM t.date)=%s
        ORDER BY t.date, t.installment_number
    """, (ano, mes))

    if not transacoes:
        st.info("Nenhuma transação neste mês.")
    else:
        df = pd.DataFrame(transacoes)
        df["Valor"] = df["amount"].astype(float).apply(fmt_brl)
        df["Data"] = pd.to_datetime(df["date"]).dt.strftime("%d/%m/%Y")
        df["Parcela"] = df.apply(lambda x: f"{x['installment_number']}/{x['installments']}" if x['installments'] and x['installments']>0 else "-", axis=1)
        df["Abatido"] = df["deducted_from_balance"].apply(lambda x: "Sim" if x else "Não")

        # Mostrar tabela compacta com scroll
        st.dataframe(
            df[["id", "type", "categoria", "Valor", "Data", "description", "status", "Parcela", "Abatido"]],
            use_container_width=True,
            hide_index=True,
            height=300
        )

        # ====== AÇÕES (com layout compacto) ======
        st.subheader("Ações")

        # Selecionar transação via dropdown
        ids = df["id"].tolist()
        selected_id = st.selectbox(
            "Selecione o ID da transação",
            ids,
            format_func=lambda x: f"ID {x} - {df[df['id']==x]['description'].iloc[0][:35]}"
        )

        col_act1, col_act2, col_act3, col_act4 = st.columns(4)

        with col_act1:
            pay_opt = st.radio("Pagamento", ["Marcar", "Abater"], horizontal=True, key="pay_opt")
            if st.button("✅ Pagar", use_container_width=True):
                deduct = (pay_opt == "Abater")
                run_query("""
                    UPDATE transactions
                    SET status='Pago', paid_date=%s, deducted_from_balance=%s
                    WHERE id=%s AND type='Despesa'
                """, (date.today(), deduct, selected_id), fetch=False)
                st.success("Atualizado!")
                st.rerun()

        with col_act2:
            if st.button("✏️ Editar", use_container_width=True):
                st.session_state.editing_id = selected_id
                st.rerun()

        with col_act3:
            if st.button("🗑️ Excluir", use_container_width=True, type="primary"):
                info = run_query("SELECT parent_id, installments FROM transactions WHERE id=%s", (selected_id,))
                if info and info[0]["parent_id"] and info[0]["installments"]>0:
                    if st.checkbox("Excluir todas as parcelas?"):
                        run_query("DELETE FROM transactions WHERE parent_id=%s", (info[0]["parent_id"],), fetch=False)
                    else:
                        run_query("DELETE FROM transactions WHERE id=%s", (selected_id,), fetch=False)
                else:
                    run_query("DELETE FROM transactions WHERE id=%s", (selected_id,), fetch=False)
                st.success("Excluído!")
                st.session_state.editing_id = None
                st.rerun()

        with col_act4:
            if st.button("👁️ Detalhes", use_container_width=True):
                tx = get_transaction(selected_id)
                if tx:
                    st.json(dict(tx))

        # ====== FORMULÁRIO DE EDIÇÃO (inline, aparece se editing_id estiver setado) ======
        if st.session_state.editing_id:
            tx = get_transaction(st.session_state.editing_id)
            if tx:
                with st.expander("✏️ Editando transação", expanded=True):
                    with st.form("edit_form", clear_on_submit=False):
                        col_e1, col_e2 = st.columns(2)
                        with col_e1:
                            tipo = st.radio("Tipo", ["Despesa","Receita"], index=0 if tx["type"]=="Despesa" else 1, horizontal=True)
                            categorias = get_categories()
                            cat_opts = {f"{c['name']} ({c['type']})": c["id"] for c in categorias}
                            default_cat = next((k for k,v in cat_opts.items() if v==tx["category_id"]), list(cat_opts.keys())[0] if cat_opts else "")
                            categoria = st.selectbox("Categoria", list(cat_opts.keys()), index=list(cat_opts.values()).index(tx["category_id"]) if tx["category_id"] in cat_opts.values() else 0)
                            valor = st.number_input("Valor (R$)", min_value=0.01, step=0.01, value=float(tx["amount"]))
                            data_trans = st.date_input("Data", value=tx["date"])
                            descricao = st.text_input("Descrição", value=tx["description"] or "")
                        with col_e2:
                            status = st.radio("Status", ["Não Pago","Pago"], index=0 if tx["status"]=="Não Pago" else 1, horizontal=True)
                            paid_date = st.date_input("Data Pagamento", value=tx["paid_date"] or date.today())
                            abatido = st.radio("Abatido", ["Não","Sim"], index=0 if not tx["deducted_from_balance"] else 1, horizontal=True)
                            if tx["installments"] and tx["installments"]>0:
                                st.info(f"Parcela {tx['installment_number']}/{tx['installments']} (campos restritos)")
                                # Desabilitar campos de edição de valor, data e descrição
                                st.markdown("""
                                <style>
                                div[data-testid="stNumberInput"] input { background-color: #f0f0f0; }
                                div[data-testid="stDateInput"] input { background-color: #f0f0f0; }
                                </style>
                                """, unsafe_allow_html=True)
                        col_b1, col_b2 = st.columns(2)
                        with col_b1:
                            if st.form_submit_button("💾 Salvar"):
                                if not categorias:
                                    st.error("Categorias necessárias.")
                                else:
                                    cat_id = cat_opts[categoria]
                                    new_paid = paid_date if status=="Pago" else None
                                    new_abatido = (abatido=="Sim")
                                    if tx["installments"] and tx["installments"]>0:
                                        # Só permite alterar status, paid_date, deducted
                                        run_query("""
                                            UPDATE transactions
                                            SET status=%s, paid_date=%s, deducted_from_balance=%s
                                            WHERE id=%s
                                        """, (status, new_paid, new_abatido, tx["id"]), fetch=False)
                                    else:
                                        run_query("""
                                            UPDATE transactions
                                            SET type=%s, category_id=%s, amount=%s, date=%s,
                                                description=%s, status=%s, paid_date=%s,
                                                deducted_from_balance=%s
                                            WHERE id=%s
                                        """, (tipo, cat_id, valor, data_trans, descricao,
                                              status, new_paid, new_abatido, tx["id"]), fetch=False)
                                    st.success("Atualizado!")
                                    st.session_state.editing_id = None
                                    st.rerun()
                        with col_b2:
                            if st.form_submit_button("❌ Cancelar"):
                                st.session_state.editing_id = None
                                st.rerun()

        # ====== GRÁFICOS ======
        st.subheader("Gráficos")
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            fig1 = go.Figure(go.Bar(
                x=["Receitas", "Despesas Abatidas"],
                y=[total_rec, desp_abatidas],
                marker_color=["#2ecc71", "#e74c3c"]
            ))
            fig1.update_layout(title="Resumo do Mês", yaxis_title="R$", height=250)
            st.plotly_chart(fig1, use_container_width=True)
        with col_g2:
            cat_data = run_query("""
                SELECT COALESCE(c.name, 'Sem Categoria') as nome, SUM(t.amount) as total
                FROM transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.user_id=1 AND t.type='Despesa'
                  AND EXTRACT(YEAR FROM t.date)=%s AND EXTRACT(MONTH FROM t.date)=%s
                GROUP BY c.name ORDER BY total DESC
            """, (ano, mes))
            if cat_data:
                df_cat = pd.DataFrame(cat_data)
                df_cat["total"] = df_cat["total"].astype(float)
                fig2 = px.bar(df_cat, x="nome", y="total", title="Despesas por Categoria",
                              color="nome", color_discrete_sequence=px.colors.qualitative.Set2)
                fig2.update_layout(height=250)
                st.plotly_chart(fig2, use_container_width=True)

# ============================================================
# 2. NOVA TRANSAÇÃO
# ============================================================
elif menu == "➕ Nova Transação":
    st.header("➕ Nova Transação")
    categorias = get_categories()
    cat_opts = {f"{c['name']} ({c['type']})": c["id"] for c in categorias} if categorias else {}

    with st.form("form_nova", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            tipo = st.radio("Tipo", ["Despesa","Receita"], horizontal=True)
            if not cat_opts:
                st.warning("Crie categorias primeiro.")
                categoria = st.selectbox("Categoria", ["Nenhuma"])
            else:
                categoria = st.selectbox("Categoria", list(cat_opts.keys()))
            valor = st.number_input("Valor (R$)", min_value=0.01, step=0.01, format="%.2f")
            data_trans = st.date_input("Data", value=date.today())
        with col2:
            descricao = st.text_input("Descrição")
            parcelas = st.selectbox("Parcelas (0=à vista)", [0,2,3,4,5,6,12])
        enviar = st.form_submit_button("Cadastrar")

        if enviar:
            if not cat_opts:
                st.error("Adicione categorias primeiro.")
            else:
                cat_id = cat_opts[categoria]
                try:
                    if parcelas>1 and tipo=="Despesa":
                        amount_per = round(valor/parcelas, 2)
                        last_amount = round(valor - amount_per*(parcelas-1), 2)
                        parent_id = str(uuid.uuid4())
                        for i in range(parcelas):
                            inst_date = add_months(data_trans, i)
                            amount = last_amount if i==parcelas-1 else amount_per
                            desc = f"{descricao} (Parcela {i+1}/{parcelas})"
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
                    st.success("Transação cadastrada!")
                except Exception as e:
                    st.error(f"Erro: {e}")

# ============================================================
# 3. GERENCIAR CATEGORIAS
# ============================================================
elif menu == "🏷️ Categorias":
    st.header("🏷️ Categorias")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Nova Categoria")
        with st.form("form_cat"):
            nome = st.text_input("Nome")
            tipo_cat = st.radio("Tipo", ["Despesa","Receita"], horizontal=True)
            if st.form_submit_button("Adicionar"):
                if nome.strip():
                    run_query("INSERT INTO categories (name, type) VALUES (%s,%s) ON CONFLICT DO NOTHING", (nome.strip(), tipo_cat), fetch=False)
                    st.success("Adicionada!")
                    st.rerun()
    with col2:
        st.subheader("Lista")
        cats = get_categories()
        if cats:
            df_cats = pd.DataFrame(cats)
            st.dataframe(df_cats, use_container_width=True, hide_index=True, height=300)
            id_del = st.number_input("ID para excluir", min_value=1, step=1)
            if st.button("Excluir"):
                uso = run_query("SELECT COUNT(*) as total FROM transactions WHERE category_id=%s", (id_del,))
                if uso and uso[0]["total"]>0:
                    st.error("Em uso, não pode excluir.")
                else:
                    run_query("DELETE FROM categories WHERE id=%s", (id_del,), fetch=False)
                    st.success("Excluída!")
                    st.rerun()
        else:
            st.info("Nenhuma categoria.")

# ============================================================
# 4. TODAS AS TRANSAÇÕES (com filtros)
# ============================================================
elif menu == "📋 Todas":
    st.header("📋 Todas as Transações")

    with st.expander("Filtros", expanded=True):
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        with col_f1:
            filtro_tipo = st.selectbox("Tipo", ["Todos", "Despesa", "Receita"])
        with col_f2:
            cats = get_categories()
            cat_list = ["Todas"] + [c["name"] for c in cats]
            filtro_cat = st.selectbox("Categoria", cat_list)
        with col_f3:
            filtro_status = st.selectbox("Status", ["Todos", "Pago", "Não Pago"])
        with col_f4:
            search = st.text_input("Descrição", placeholder="Buscar...")

    query = """
        SELECT t.id, t.type, COALESCE(c.name, 'Sem Categoria') as categoria,
               t.amount, t.date, t.description, t.status, t.paid_date,
               CASE WHEN t.installments>0 THEN t.installment_number||'/'||t.installments ELSE '-' END as parcela,
               CASE WHEN t.deducted_from_balance THEN 'Sim' ELSE 'Não' END as abatido
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = 1
    """
    params, cond = [], []
    if filtro_tipo != "Todos":
        cond.append("t.type=%s"); params.append(filtro_tipo)
    if filtro_cat != "Todas":
        cat_id = next((c["id"] for c in cats if c["name"]==filtro_cat), None)
        if cat_id:
            cond.append("t.category_id=%s"); params.append(cat_id)
    if filtro_status != "Todos":
        cond.append("t.status=%s"); params.append(filtro_status)
    if search:
        cond.append("t.description ILIKE %s"); params.append(f"%{search}%")
    if cond:
        query += " AND " + " AND ".join(cond)
    query += " ORDER BY t.date DESC, t.installment_number"

    todas = run_query(query, tuple(params))
    if todas:
        df = pd.DataFrame(todas)
        df["Valor"] = df["amount"].astype(float).apply(fmt_brl)
        df["Data"] = pd.to_datetime(df["date"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            df[["id","type","categoria","Valor","Data","description","status","parcela","abatido"]],
            use_container_width=True,
            hide_index=True,
            height=400
        )
        st.caption(f"Total: {len(df)} transações")
    else:
        st.info("Nenhuma transação encontrada.")

# ============================================================
# 5. TOTAIS GERAIS
# ============================================================
elif menu == "📈 Totais":
    st.header("📈 Totais Gerais")

    total_naopago = run_query("SELECT COALESCE(SUM(amount),0) as total FROM transactions WHERE user_id=1 AND type='Despesa' AND status='Não Pago'")
    total_unpaid = total_naopago[0]["total"] if total_naopago else 0.0

    ano_atual = date.today().year
    receitas_ano = run_query("SELECT COALESCE(SUM(amount),0) as total FROM transactions WHERE user_id=1 AND type='Receita' AND EXTRACT(YEAR FROM date)=%s", (ano_atual,))
    total_rec = receitas_ano[0]["total"] if receitas_ano else 0.0

    despesas_ano = run_query("SELECT COALESCE(SUM(amount),0) as total FROM transactions WHERE user_id=1 AND type='Despesa' AND deducted_from_balance=TRUE AND EXTRACT(YEAR FROM date)=%s", (ano_atual,))
    total_desp = despesas_ano[0]["total"] if despesas_ano else 0.0

    saldo_ano = total_rec - total_desp

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Não Pagos (Geral)", fmt_brl(total_unpaid))
    c2.metric(f"Receitas {ano_atual}", fmt_brl(total_rec))
    c3.metric(f"Despesas {ano_atual}", fmt_brl(total_desp))
    c4.metric("Saldo Ano", fmt_brl(saldo_ano), delta_color="normal" if saldo_ano>=0 else "inverse")

    # Evolução mensal
    st.subheader("Evolução Mensal")
    evol = run_query("""
        SELECT DATE_TRUNC('month', date) as mes,
               COALESCE(SUM(CASE WHEN type='Receita' THEN amount ELSE 0 END),0) as receitas,
               COALESCE(SUM(CASE WHEN type='Despesa' AND deducted_from_balance THEN amount ELSE 0 END),0) as despesas
        FROM transactions
        WHERE user_id=1 AND EXTRACT(YEAR FROM date)=%s
        GROUP BY mes ORDER BY mes
    """, (ano_atual,))
    if evol:
        df_evol = pd.DataFrame(evol)
        df_evol["mes"] = pd.to_datetime(df_evol["mes"]).dt.strftime("%b/%y")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_evol["mes"], y=df_evol["receitas"], name="Receitas", marker_color="#2ecc71"))
        fig.add_trace(go.Bar(x=df_evol["mes"], y=df_evol["despesas"], name="Despesas", marker_color="#e74c3c"))
        fig.update_layout(barmode="group", height=350)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sem dados para este ano.")