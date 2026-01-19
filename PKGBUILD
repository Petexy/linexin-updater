# Maintainer: Petexy <https://github.com/Petexy>

pkgname=linexin-updater
pkgver=3.5.8.r
pkgrel=1
_currentdate=$(date +"%Y-%m-%d%H-%M-%S")
pkgdesc='An updater for Arch-based distros. One button updates system packages and Flatpaks at once'
url='https://github.com/Petexy'
arch=(x86_64)
license=('GPL-3.0')
depends=(
  python-gobject
  gtk4
  libadwaita
  linexin-center
  linexin-upgrade-tool
  wget
)
makedepends=(
)
install="${pkgname}.install"

package() {
   mkdir -p ${pkgdir}/usr/share/linexin/widgets
   mkdir -p ${pkgdir}/usr/bin
   mkdir -p ${pkgdir}/usr/applications
   mkdir -p ${pkgdir}/usr/icons   
   cp -rf ${srcdir}/usr/ ${pkgdir}/
   mv ${pkgdir}/usr/share/icons/archlinux-logo-text.svg ${pkgdir}/usr/share/pixmaps/archlinux-logo-text.svg 2>/dev/null || true
   mv ${pkgdir}/usr/share/icons/archlinux-logo-text-dark.svg ${pkgdir}/usr/share/pixmaps/archlinux-logo-text-dark.svg 2>/dev/null || true
   mv ${pkgdir}/usr/tmp/ ${pkgdir}/usr/share/
}
