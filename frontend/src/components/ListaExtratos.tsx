import { FileText, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ErroApi, apagaExtrato, listaExtratos } from '../api/cliente'
import type { ExtratoEnviado } from '../api/tipos'
import { formataData, plural, rotuloFormato } from '../utils/formatacao'
import estilos from './ListaExtratos.module.css'

type Props = {
  /** Muda a cada importação concluída: a lista é recarregada. */
  versao: number
  /** Avisado depois de excluir um extrato (ex.: para limpar um erro de "já importado"). */
  onExcluido?: () => void
}

const dataHora = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' })

function periodo({ periodo_inicio, periodo_fim }: ExtratoEnviado): string | null {
  if (periodo_inicio && periodo_fim) return `${formataData(periodo_inicio)} a ${formataData(periodo_fim)}`
  if (periodo_inicio) return `a partir de ${formataData(periodo_inicio)}`
  if (periodo_fim) return `até ${formataData(periodo_fim)}`
  return null
}

function mensagemDe(erro: unknown): string {
  return erro instanceof ErroApi ? erro.message : 'Não foi possível falar com a API. Tente de novo.'
}

/** Extratos já importados pelo usuário, com exclusão (libera o mesmo arquivo para nova importação). */
export function ListaExtratos({ versao, onExcluido }: Props) {
  const [extratos, setExtratos] = useState<ExtratoEnviado[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [confirmando, setConfirmando] = useState<string | null>(null)
  const [excluindo, setExcluindo] = useState<string | null>(null)

  useEffect(() => {
    let ativo = true
    listaExtratos()
      .then((lista) => {
        if (!ativo) return
        setExtratos(lista)
        setErro(null)
      })
      .catch((e) => ativo && setErro(mensagemDe(e)))
    return () => {
      ativo = false
    }
  }, [versao])

  async function excluir(id: string) {
    setExcluindo(id)
    setErro(null)
    try {
      await apagaExtrato(id)
      setExtratos((atual) => atual?.filter((e) => e.id !== id) ?? null)
      setConfirmando(null)
      onExcluido?.()
    } catch (e) {
      setErro(mensagemDe(e))
    } finally {
      setExcluindo(null)
    }
  }

  return (
    <section id="extratos-importados" className={estilos.painel} aria-labelledby="titulo-extratos">
      <div className={estilos.topo}>
        <h2 id="titulo-extratos">Extratos importados</h2>
        <p>Excluir um extrato remove as transações dele e permite importar o mesmo arquivo de novo.</p>
      </div>

      {erro && (
        <p className={estilos.erro} role="alert">
          {erro}
        </p>
      )}

      {extratos === null && !erro && <p className={estilos.vazio}>Carregando…</p>}

      {extratos?.length === 0 && <p className={estilos.vazio}>Nenhum extrato importado ainda.</p>}

      {extratos && extratos.length > 0 && (
        <ul className={estilos.lista}>
          {extratos.map((e) => {
            const per = periodo(e)
            const ocupado = excluindo === e.id
            return (
              <li key={e.id} className={estilos.item}>
                <FileText size={22} className={estilos.icone} aria-hidden="true" />
                <div className={estilos.info}>
                  <strong className={estilos.nome}>{e.nome_arquivo || 'Arquivo sem nome'}</strong>
                  <span className={estilos.detalhes}>
                    {rotuloFormato(e.parser)}
                    {per && ` · ${per}`}
                    {` · ${plural(e.linhas_gravadas, 'transação', 'transações')}`}
                    {` · enviado em ${dataHora.format(new Date(e.enviado_em))}`}
                  </span>
                </div>

                {confirmando === e.id ? (
                  <div className={estilos.confirmacao} role="group" aria-label="Confirmar exclusão">
                    <span>
                      Excluir? {plural(e.linhas_gravadas, 'transação será removida', 'transações serão removidas')}.
                    </span>
                    <button
                      type="button"
                      className={estilos.cancelar}
                      onClick={() => setConfirmando(null)}
                      disabled={ocupado}
                    >
                      Cancelar
                    </button>
                    <button
                      type="button"
                      className={estilos.confirmar}
                      onClick={() => void excluir(e.id)}
                      disabled={ocupado}
                    >
                      {ocupado ? 'Excluindo…' : 'Excluir'}
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className={estilos.excluir}
                    onClick={() => setConfirmando(e.id)}
                    aria-label={`Excluir o extrato "${e.nome_arquivo}"`}
                  >
                    <Trash2 size={18} aria-hidden="true" /> Excluir
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
