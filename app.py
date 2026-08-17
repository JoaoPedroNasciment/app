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
        # Fallback local (substitua pela sua URL)
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
def format_brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def add_months(d, months):
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def get_categories():
    result = run_query("SELECT id, name, type FROM categories ORDER BY type, name")
    return result if result else []

def get_transaction_by_id(tx_id):
    result = run_query("""
        SELECT id, type, category_id, amount, date, description, status, paid_date,
               installments, installment_number, parent_id, deducted_from_balance
        FROM transactions WHERE id = %s
    """, (tx_id,))
    return result[0] if result else None

# ============================================================
# INICIALIZAÇÃO DE SESSION STATE
# ============================================================
if "selected_tx_id" not in st.session_state:
    st.session_state.selected_tx_id = None
if "edit_mode" not in st.session_state:
    st.session_state.edit_mode = False
if "view_month" not in st.session_state:
    st.session_state.view_month = date.today()

# ============================================================
# PÁGINA PRINCIPAL
# ============================================================
st.set_page_config(page_title="Gerenciador Financeiro", page_icon="💰", layout="wide")
st.title("💰 Gerenciador Financeiro")

# Sidebar
menu = st.sidebar.radio(
    "Menu",
    ["Visão do Mês", "Adicionar Transação", "Gerenciar Categorias", "Todas as Transações", "Totais Gerais"]
)

# ============================================================
# 1. VISÃO DO MÊS
# ============================================================
if menu == "Visão do Mês":
    st.header("📅 Visão do Mês")

    # Seleção de mês
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        mes_selecionado = st.date_input(
            "Selecione o mês",
            value=st.session_state.view_month,
            format="DD/MM/YYYY",
            key="month_picker"
        )
        st.session_state.view_month = mes_selecionado

    ano = mes_selecionado.year
    mes = mes_selecionado.month
    nome_mes = mes_selecionado.strftime("%B/%Y").capitalize()

    # Resumo do mês
    resumo = run_query("""
        SELECT type, COALESCE(SUM(amount), 0) as total
        FROM transactions
        WHERE user_id = 1
          AND EXTRACT(YEAR FROM date) = %s
          AND EXTRACT(MONTH FROM date) = %s
        GROUP BY type
    """, (ano, mes))
    summary = {"Despesa": 0.0, "Receita": 0.0}
    if resumo:
        for r in resumo:
            summary[r["type"]] = float(r["total"])

    abatidas = run_query("""
        SELECT COALESCE(SUM(amount), 0) as total
        FROM transactions
        WHERE user_id = 1 AND type = 'Despesa'
          AND EXTRACT(YEAR FROM date) = %s
          AND EXTRACT(MONTH FROM date) = %s
          AND deducted_from_balance = TRUE
    """, (ano, mes))
    deducted = float(abatidas[0]["total"]) if abatidas else 0.0

    nao_pagas = run_query("""
        SELECT COALESCE(SUM(amount), 0) as total, COUNT(*) as qtd
        FROM transactions
        WHERE user_id = 1 AND type = 'Despesa'
          AND EXTRACT(YEAR FROM date) = %s
          AND EXTRACT(MONTH FROM date) = %s
          AND status = 'Não Pago'
    """, (ano, mes))
    unpaid_total = float(nao_pagas[0]["total"]) if nao_pagas else 0.0
    unpaid_count = nao_pagas[0]["qtd"] if nao_pagas else 0

    saldo = summary["Receita"] - deducted

    # Cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Receitas", format_brl(summary["Receita"]))
    c2.metric("Despesas Abatidas", format_brl(deducted))
    c3.metric("Saldo", format_brl(saldo), delta_color="normal" if saldo >= 0 else "inverse")
    c4.metric("Não Pagas (Mês)", format_brl(unpaid_total))

    if unpaid_count > 0:
        st.warning(f"⚠ {unpaid_count} transação(ões) não paga(s) neste mês")
    else:
        st.success("✓ Todas as transações pagas neste mês")

    # Tabela de transações
    st.subheader(f"Transações de {nome_mes}")

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
        df["amount"] = df["amount"].astype(float)
        df["Data"] = pd.to_datetime(df["date"]).dt.strftime("%d/%m/%Y")
        df["Valor"] = df["amount"].apply(format_brl)
        df["Parcela"] = df.apply(
            lambda x: f"{x['installment_number']}/{x['installments']}" if x["installments"] and x["installments"] > 0 else "-",
            axis=1
        )
        df["Abatido"] = df["deducted_from_balance"].apply(lambda x: "Sim" if x else "Não")

        st.dataframe(
            df[["id", "type", "categoria", "Valor", "Data", "description", "status", "Parcela", "Abatido"]].rename(columns={
                "id": "ID", "type": "Tipo", "categoria": "Categoria",
                "description": "Descrição", "status": "Status"
            }),
            use_container_width=True,
            hide_index=True
        )

        # Seleção e ações
        st.subheader("Ações")
        ids = df["id"].tolist()
        if ids:
            selected_id = st.selectbox("Selecione a transação pelo ID", ids, format_func=lambda x: f"ID {x} - {df[df['id']==x]['description'].iloc[0][:30]}...")
            st.session_state.selected_tx_id = selected_id

            col_a, col_b, col_c, col_d = st.columns(4)

            # Marcar como Pago
            with col_a:
                opcao = st.radio("Opção de pagamento", ["Apenas marcar", "Marcar e Abater"], key="pay_option")
                if st.button("Marcar como Pago"):
                    deduct = (opcao == "Marcar e Abater")
                    run_query("""
                        UPDATE transactions
                        SET status = 'Pago', paid_date = %s, deducted_from_balance = %s
                        WHERE id = %s AND type = 'Despesa'
                    """, (date.today(), deduct, selected_id), fetch=False)
                    st.success("Transação atualizada!")
                    st.rerun()

            # Editar
            with col_b:
                if st.button("Editar Transação"):
                    st.session_state.edit_mode = True
                    st.rerun()

            # Excluir
            with col_c:
                if st.button("Excluir Transação", type="primary"):
                    info = run_query("SELECT parent_id, installments FROM transactions WHERE id = %s", (selected_id,))
                    if info and info[0]["parent_id"] and info[0]["installments"] > 0:
                        if st.checkbox("Excluir TODAS as parcelas deste grupo?"):
                            run_query("DELETE FROM transactions WHERE parent_id = %s", (info[0]["parent_id"],), fetch=False)
                        else:
                            run_query("DELETE FROM transactions WHERE id = %s", (selected_id,), fetch=False)
                    else:
                        run_query("DELETE FROM transactions WHERE id = %s", (selected_id,), fetch=False)
                    st.success("Excluído!")
                    st.session_state.selected_tx_id = None
                    st.rerun()

            # Ver detalhes
            with col_d:
                if st.button("Ver Detalhes"):
                    tx = get_transaction_by_id(selected_id)
                    if tx:
                        st.json(dict(tx))

            # ===== EDITAR TRANSAÇÃO (se ativado) =====
            if st.session_state.edit_mode and st.session_state.selected_tx_id:
                tx = get_transaction_by_id(st.session_state.selected_tx_id)
                if tx:
                    st.subheader("✏️ Editar Transação")
                    with st.form("edit_form"):
                        col_e1, col_e2 = st.columns(2)
                        with col_e1:
                            tipo = st.radio("Tipo", ["Despesa", "Receita"], index=0 if tx["type"]=="Despesa" else 1, key="edit_tipo")
                            categorias = get_categories()
                            cat_opts = {f"{c['name']} ({c['type']})": c["id"] for c in categorias}
                            default_cat = None
                            for k, v in cat_opts.items():
                                if v == tx["category_id"]:
                                    default_cat = k
                                    break
                            categoria = st.selectbox("Categoria", list(cat_opts.keys()), index=list(cat_opts.values()).index(tx["category_id"]) if tx["category_id"] in cat_opts.values() else 0, key="edit_cat")
                            valor = st.number_input("Valor (R$)", min_value=0.01, step=0.01, value=float(tx["amount"]), key="edit_valor")
                            data_trans = st.date_input("Data", value=tx["date"], key="edit_data")
                            descricao = st.text_input("Descrição", value=tx["description"] or "", key="edit_desc")
                        with col_e2:
                            status = st.radio("Status", ["Não Pago", "Pago"], index=0 if tx["status"]=="Não Pago" else 1, key="edit_status")
                            paid_date = st.date_input("Data Pagamento", value=tx["paid_date"] or date.today(), key="edit_paid")
                            abatido = st.radio("Abatido do Saldo", ["Não", "Sim"], index=0 if not tx["deducted_from_balance"] else 1, key="edit_abatido")

                            is_installment = tx["installments"] and tx["installments"] > 0
                            if is_installment:
                                st.info(f"Parcela {tx['installment_number']}/{tx['installments']} - Campos editáveis restritos")
                                # Desabilitar alguns campos
                                st.markdown("""
                                <style>
                                div[data-testid="stNumberInput"] > div > div > input { background-color: #f0f0f0; }
                                div[data-testid="stDateInput"] > div > div > input { background-color: #f0f0f0; }
                                </style>
                                """, unsafe_allow_html=True)

                        enviar = st.form_submit_button("Salvar Alterações")

                        if enviar:
                            if not categorias:
                                st.error("Adicione categorias primeiro.")
                            else:
                                cat_id = cat_opts[categoria]
                                new_paid = paid_date if status == "Pago" else None
                                new_abatido = (abatido == "Sim")
                                # Se for parcela, só permite alterar status, paid_date, deducted
                                if is_installment:
                                    run_query("""
                                        UPDATE transactions
                                        SET status = %s, paid_date = %s, deducted_from_balance = %s
                                        WHERE id = %s
                                    """, (status, new_paid, new_abatido, tx["id"]), fetch=False)
                                else:
                                    run_query("""
                                        UPDATE transactions
                                        SET type = %s, category_id = %s, amount = %s, date = %s,
                                            description = %s, status = %s, paid_date = %s,
                                            deducted_from_balance = %s
                                        WHERE id = %s
                                    """, (tipo, cat_id, valor, data_trans, descricao,
                                          status, new_paid, new_abatido, tx["id"]), fetch=False)
                                st.success("Transação atualizada!")
                                st.session_state.edit_mode = False
                                st.rerun()

                    if st.button("Cancelar Edição"):
                        st.session_state.edit_mode = False
                        st.rerun()

        # Gráficos
        st.subheader("Gráficos")
        col_g1, col_g2 = st.columns(2)

        with col_g1:
            fig1 = go.Figure(data=[
                go.Bar(x=["Receitas", "Despesas Abatidas"],
                       y=[summary["Receita"], deducted],
                       marker_color=["#2ecc71", "#e74c3c"])
            ])
            fig1.update_layout(title="Resumo do Mês", yaxis_title="Valor (R$)")
            st.plotly_chart(fig1, use_container_width=True)

        with col_g2:
            cat_data = run_query("""
                SELECT COALESCE(c.name, 'Sem Categoria') as nome, SUM(t.amount) as total
                FROM transactions t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.user_id = 1 AND t.type = 'Despesa'
                  AND EXTRACT(YEAR FROM t.date) = %s
                  AND EXTRACT(MONTH FROM t.date) = %s
                GROUP BY c.name
                ORDER BY total DESC
            """, (ano, mes))
            if cat_data:
                df_cat = pd.DataFrame(cat_data)
                df_cat["total"] = df_cat["total"].astype(float)
                fig2 = px.bar(df_cat, x="nome", y="total", title="Despesas por Categoria",
                              color="nome", color_discrete_sequence=px.colors.qualitative.Set2)
                st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Nenhuma transação encontrada neste mês.")

# ============================================================
# 2. ADICIONAR TRANSAÇÃO
# ============================================================
elif menu == "Adicionar Transação":
    st.header("➕ Adicionar Transação")

    categorias = get_categories()
    cat_options = {f"{c['name']} ({c['type']})": c["id"] for c in categorias} if categorias else {}

    with st.form("form_transacao", clear_on_submit=True):
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        if not cat_options:
            st.warning("Nenhuma categoria cadastrada. Vá em 'Gerenciar Categorias' para adicionar.")
            categoria = st.selectbox("Categoria", ["Nenhuma categoria"])
        else:
            categoria = st.selectbox("Categoria", list(cat_options.keys()))
        valor = st.number_input("Valor (R$)", min_value=0.01, step=0.01, format="%.2f")
        data_trans = st.date_input("Data", value=date.today())
        descricao = st.text_input("Descrição")
        parcelas = st.selectbox("Parcelas (0 = à vista)", [0, 2, 3, 4, 5, 6, 12])

        enviado = st.form_submit_button("Cadastrar Transação")

        if enviado:
            if not cat_options:
                st.error("Adicione categorias primeiro.")
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

                    st.success("Transação cadastrada com sucesso!")
                except Exception as e:
                    st.error(f"Erro: {e}")

# ============================================================
# 3. GERENCIAR CATEGORIAS
# ============================================================
elif menu == "Gerenciar Categorias":
    st.header("🏷️ Gerenciar Categorias")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Nova Categoria")
        with st.form("form_categoria"):
            nome = st.text_input("Nome")
            tipo_cat = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
            if st.form_submit_button("Adicionar"):
                if nome.strip():
                    run_query("""
                        INSERT INTO categories (name, type)
                        VALUES (%s, %s)
                        ON CONFLICT (name, type) DO NOTHING
                    """, (nome.strip(), tipo_cat), fetch=False)
                    st.success("Categoria adicionada!")
                    st.rerun()
                else:
                    st.warning("Digite um nome")

    with col2:
        st.subheader("Categorias existentes")
        cats = get_categories()
        if cats:
            df_cats = pd.DataFrame(cats)
            st.dataframe(df_cats, use_container_width=True, hide_index=True)

            id_del = st.number_input("ID para excluir", min_value=1, step=1)
            if st.button("Excluir Categoria"):
                uso = run_query("SELECT COUNT(*) as total FROM transactions WHERE category_id = %s", (id_del,))
                if uso and uso[0]["total"] > 0:
                    st.error("Categoria está em uso e não pode ser excluída.")
                else:
                    run_query("DELETE FROM categories WHERE id = %s", (id_del,), fetch=False)
                    st.success("Categoria excluída!")
                    st.rerun()
        else:
            st.info("Nenhuma categoria cadastrada.")

# ============================================================
# 4. TODAS AS TRANSAÇÕES
# ============================================================
elif menu == "Todas as Transações":
    st.header("📋 Todas as Transações")

    # Filtros
    with st.expander("Filtros", expanded=True):
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        with col_f1:
            filtro_tipo = st.selectbox("Tipo", ["Todos", "Despesa", "Receita"])
        with col_f2:
            categorias = get_categories()
            cat_list = ["Todas"] + [c["name"] for c in categorias]
            filtro_cat = st.selectbox("Categoria", cat_list)
        with col_f3:
            filtro_status = st.selectbox("Status", ["Todos", "Pago", "Não Pago"])
        with col_f4:
            search_text = st.text_input("Buscar (descrição)", placeholder="Digite parte da descrição")

    # Montar query
    query = """
        SELECT t.id, t.type, COALESCE(c.name, 'Sem Categoria') as categoria,
               t.amount, t.date, t.description, t.status, t.paid_date,
               CASE WHEN t.installments > 0 THEN t.installment_number || '/' || t.installments ELSE '-' END as parcela,
               CASE WHEN t.deducted_from_balance THEN 'Sim' ELSE 'Não' END as abatido
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.user_id = 1
    """
    params = []
    conditions = []

    if filtro_tipo != "Todos":
        conditions.append("t.type = %s")
        params.append(filtro_tipo)
    if filtro_cat != "Todas":
        # Pega o id da categoria
        cat_id = None
        for c in categorias:
            if c["name"] == filtro_cat:
                cat_id = c["id"]
                break
        if cat_id:
            conditions.append("t.category_id = %s")
            params.append(cat_id)
    if filtro_status != "Todos":
        conditions.append("t.status = %s")
        params.append(filtro_status)
    if search_text:
        conditions.append("t.description ILIKE %s")
        params.append(f"%{search_text}%")

    if conditions:
        query += " AND " + " AND ".join(conditions)

    query += " ORDER BY t.date DESC, t.installment_number"

    todas = run_query(query, tuple(params))

    if todas:
        df = pd.DataFrame(todas)
        df["amount"] = df["amount"].astype(float)
        df["Valor"] = df["amount"].apply(format_brl)
        df["Data"] = pd.to_datetime(df["date"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            df[["id", "type", "categoria", "Valor", "Data", "description", "status", "parcela", "abatido"]].rename(columns={
                "id": "ID", "type": "Tipo", "categoria": "Categoria",
                "description": "Descrição", "status": "Status", "parcela": "Parcela", "abatido": "Abatido"
            }),
            use_container_width=True,
            hide_index=True
        )
        st.caption(f"Total de {len(df)} transações")
    else:
        st.info("Nenhuma transação encontrada com os filtros atuais.")

# ============================================================
# 5. TOTAIS GERAIS
# ============================================================
elif menu == "Totais Gerais":
    st.header("📊 Totais Gerais")

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
        WHERE user_id = 1 AND type = 'Receita'
          AND EXTRACT(YEAR FROM date) = %s
    """, (ano_atual,))
    total_receitas = float(receitas_ano[0]["total"]) if receitas_ano else 0.0

    despesas_ano = run_query("""
        SELECT COALESCE(SUM(amount), 0) as total
        FROM transactions
        WHERE user_id = 1 AND type = 'Despesa'
          AND EXTRACT(YEAR FROM date) = %s
          AND deducted_from_balance = TRUE
    """, (ano_atual,))
    total_despesas = float(despesas_ano[0]["total"]) if despesas_ano else 0.0

    saldo_ano = total_receitas - total_despesas

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Não Pagos (Geral)", format_brl(total_unpaid))
    col2.metric(f"Receitas do Ano ({ano_atual})", format_brl(total_receitas))
    col3.metric(f"Despesas Abatidas do Ano", format_brl(total_despesas))
    col4.metric("Saldo do Ano", format_brl(saldo_ano), delta_color="normal" if saldo_ano >= 0 else "inverse")

    # Gráfico de evolução mensal
    st.subheader("Evolução Mensal")
    evol = run_query("""
        SELECT DATE_TRUNC('month', date) as mes,
               COALESCE(SUM(CASE WHEN type = 'Receita' THEN amount ELSE 0 END), 0) as receitas,
               COALESCE(SUM(CASE WHEN type = 'Despesa' AND deducted_from_balance THEN amount ELSE 0 END), 0) as despesas
        FROM transactions
        WHERE user_id = 1
          AND EXTRACT(YEAR FROM date) = %s
        GROUP BY mes
        ORDER BY mes
    """, (ano_atual,))
    if evol:
        df_evol = pd.DataFrame(evol)
        df_evol["mes"] = pd.to_datetime(df_evol["mes"]).dt.strftime("%b/%Y")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_evol["mes"], y=df_evol["receitas"], name="Receitas", marker_color="#2ecc71"))
        fig.add_trace(go.Bar(x=df_evol["mes"], y=df_evol["despesas"], name="Despesas Abatidas", marker_color="#e74c3c"))
        fig.update_layout(barmode="group", title=f"Evolução {ano_atual}", xaxis_title="Mês", yaxis_title="Valor (R$)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sem dados para este ano.")