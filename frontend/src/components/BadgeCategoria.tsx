import { rotuloCategoria } from '../utils/formatacao'
import estilos from './BadgeCategoria.module.css'

type Props = {
  categoria: string | null
}

/** Selo da categoria. De onde ela veio (regra, mapa, modelo) não aparece para o usuário. */
export function BadgeCategoria({ categoria }: Props) {
  return (
    <span className={categoria ? estilos.badge : `${estilos.badge} ${estilos.vazia}`}>
      {categoria ? rotuloCategoria(categoria) : 'Sem categoria'}
    </span>
  )
}
