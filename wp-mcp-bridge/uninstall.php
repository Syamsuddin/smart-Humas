<?php
/**
 * Dijalankan saat plugin dihapus (bukan saat dinonaktifkan): bersihkan peran dan opsi.
 * Meta _wpmcp_* pada post dibiarkan sebagai jejak riwayat redaksi.
 *
 * @package wp-mcp-bridge
 */

if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
	exit;
}

remove_role( 'editor_ai' );
delete_option( 'wpmcp_empty_searches' );
