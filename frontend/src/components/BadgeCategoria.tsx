import { rotuloCategoria, rotuloOrigem } from '../utils/formatacao'
import estilos from './BadgeCategoria.module.css'

type Props = {
  categoria: string | null
  origem: string | null
}

/** Selo da categoria com a origem visível embaixo (regra fixa, mapa ou fora do mapa). */
export function BadgeCategoria({ categoria, origem }: Props) {
  return (
    <span className={estilos.celula}>
      <span className={categoria ? estilos.badge : `${estilos.badge} ${estilos.vazia}`}>
        {categoria ? rotuloCategoria(categoria) : 'Sem categoria'}
      </span>
      <span className={estilos.origem}>{rotuloOrigem(categoria ? origem : null)}</span>
    </span>
  )
}
