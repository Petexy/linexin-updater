# Maintainer: Petexy <https://github.com/Petexy>

pkgname=linexin-updater
pkgver=4.0.0.r
pkgrel=3
pkgdesc='An updater for Arch-based distros. One button updates system packages and Flatpaks at once'
url='https://github.com/Petexy'
arch=('x86_64')
license=('GPL-3.0')
depends=(
  'python-gobject'
  'gtk4'
  'libadwaita'
  'linexin-center'
  'linexin-upgrade-tool'
  'wget'
)
install="${pkgname}.install"

package() {
    cd "${srcdir}"

    find usr -type f | while IFS= read -r _file; do
        case "${_file}" in
            usr/bin/*)
                install -Dm755 "${_file}" "${pkgdir}/${_file}"
                ;;
            usr/share/icons/archlinux-logo-text.svg)
                install -Dm644 "${_file}" "${pkgdir}/usr/share/linexin/pixmaps/archlinux-logo-text.svg"
                ;;
            usr/share/icons/archlinux-logo-text-dark.svg)
                install -Dm644 "${_file}" "${pkgdir}/usr/share/linexin/pixmaps/archlinux-logo-text-dark.svg"
                ;;
            *)
                install -Dm644 "${_file}" "${pkgdir}/${_file}"
                ;;
        esac
    done
}
