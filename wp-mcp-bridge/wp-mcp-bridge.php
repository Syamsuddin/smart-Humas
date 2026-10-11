<?php
/**
 * Plugin Name:       WP-MCP Bridge
 * Plugin URI:        https://github.com/Syamsuddin/smart-humas
 * Description:       Jembatan tipis untuk WP-MCP: peran "Editor AI", meta alur kerja (_wpmcp_*), pembatasan akun AI hanya dari server sendiri, halaman Persetujuan WP-MCP untuk manusia, dan endpoint pemeriksaan. Seluruh kebijakan ada di server WP-MCP.
 * Version:           1.2.0
 * Requires at least: 6.4
 * Requires PHP:      8.0
 * Author:            Syamsuddin Ideris
 * Author URI:        mailto:syamsuddin.ideris@gmail.com
 * License:           GPL-2.0-or-later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       wp-mcp-bridge
 *
 * Plugin ini sengaja tipis dan berlisensi GPL karena berjalan di dalam WordPress.
 * Logika kebijakan, pemeriksa nama, pemasker data pribadi, dan katalog tool ada di
 * server WP-MCP (proses terpisah, lisensi komersial).
 *
 * Konstanta opsional di wp-config.php:
 *   WPMCP_BRIDGE_KEY   rahasia bersama; bila diisi, akun AI hanya diterima bila header X-WPMCP-Key cocok
 *                      (wajib bila situs berada di balik reverse proxy di server yang sama).
 *   WPMCP_ALLOWED_IPS  array IP tambahan selain 127.0.0.1/::1.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

const WPMCP_BRIDGE_VERSION = '1.2.0';
const WPMCP_ROLE           = 'editor_ai';
const WPMCP_PENDING_OPTION = 'wpmcp_pending_actions';

function wpmcp_post_meta_keys(): array {
	return array(
		'_wpmcp_state', '_wpmcp_drafted_by', '_wpmcp_revised_by', '_wpmcp_revision_requests', '_wpmcp_submitted_by',
		'_wpmcp_submitted_at', '_wpmcp_reviewer_note', '_wpmcp_leader_edits', '_wpmcp_approved_by', '_wpmcp_published_by',
		'_wpmcp_delegation_id', '_wpmcp_corrections', '_wpmcp_withdrawn', '_wpmcp_source_note',
	);
}

/**
 * Hak peran Editor AI. Hak teknis menerbitkan ada, tetapi WP-MCP hanya menjalankannya atas persetujuan
 * pimpinan (atau delegasinya). Tidak ada hak tema, plugin, pengguna, opsi, atau unfiltered_html.
 */
function wpmcp_role_caps(): array {
	return array(
		'read'                 => true,
		'upload_files'         => true,
		'edit_posts'           => true,
		'edit_others_posts'    => true,
		'edit_published_posts' => true,
		'publish_posts'        => true,
		'delete_posts'         => true,
		'delete_others_posts'  => true,
		'edit_pages'           => true,
		'edit_others_pages'    => true,
		'edit_published_pages' => true,
		'publish_pages'        => true,
		'delete_pages'         => true,
		'delete_others_pages'  => true,
		'manage_categories'    => true,
		'moderate_comments'    => true,
		'edit_comment'         => true,
	);
}

function wpmcp_install_role(): void {
	remove_role( WPMCP_ROLE );
	add_role( WPMCP_ROLE, 'Editor AI', wpmcp_role_caps() );
	update_option( 'wpmcp_role_version', WPMCP_BRIDGE_VERSION, false );
}

register_activation_hook( __FILE__, 'wpmcp_install_role' );

/* --------------------------------------------------------------------------
 * Identitas dan asal permintaan akun AI
 * ------------------------------------------------------------------------ */
function wpmcp_user_is_ai( $user ): bool {
	return $user instanceof WP_User && $user->exists() && in_array( WPMCP_ROLE, (array) $user->roles, true );
}

function wpmcp_current_user_is_ai(): bool {
	return wpmcp_user_is_ai( wp_get_current_user() );
}

/** Permintaan datang dari server WP-MCP: IP loopback (atau terdaftar) DAN, bila diatur, header rahasia cocok. */
function wpmcp_request_from_server(): bool {
	$ip      = isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : '';
	$allowed = array( '127.0.0.1', '::1' );
	if ( defined( 'WPMCP_ALLOWED_IPS' ) && is_array( WPMCP_ALLOWED_IPS ) ) {
		$allowed = array_merge( $allowed, WPMCP_ALLOWED_IPS );
	}
	if ( ! in_array( $ip, $allowed, true ) ) {
		return false;
	}
	if ( defined( 'WPMCP_BRIDGE_KEY' ) && WPMCP_BRIDGE_KEY ) {
		$sent = isset( $_SERVER['HTTP_X_WPMCP_KEY'] ) ? (string) wp_unslash( $_SERVER['HTTP_X_WPMCP_KEY'] ) : '';
		return hash_equals( (string) WPMCP_BRIDGE_KEY, $sent );
	}
	return true;
}

add_action(
	'init',
	static function () {
		// Segarkan hak peran bila versi plugin berubah (aktivasi ulang plugin yang sudah aktif tidak memicu hook).
		if ( get_option( 'wpmcp_role_version' ) !== WPMCP_BRIDGE_VERSION ) {
			wpmcp_install_role();
		}

		$post_meta_auth = static function ( $allowed, $meta_key, $post_id ) {
			// Hanya akun AI (yang dijaga WP-MCP) atau editor ke atas; penulis biasa tidak bisa memalsukan status alur kerja.
			return current_user_can( 'edit_post', $post_id ) && ( wpmcp_current_user_is_ai() || current_user_can( 'edit_others_posts' ) );
		};
		foreach ( array( 'post', 'page' ) as $type ) {
			foreach ( wpmcp_post_meta_keys() as $key ) {
				register_post_meta( $type, $key, array(
					'type'          => 'string',
					'single'        => true,
					'show_in_rest'  => true,
					'default'       => '',
					'auth_callback' => $post_meta_auth,
				) );
			}
		}
		foreach ( array( '_wpmcp_reply_class', '_wpmcp_drafted_by' ) as $key ) {
			register_meta( 'comment', $key, array(
				'type'          => 'string',
				'single'        => true,
				'show_in_rest'  => true,
				'default'       => '',
				'auth_callback' => static function () {
					return current_user_can( 'moderate_comments' );
				},
			) );
		}
	}
);

/*
 * Akun AI ditolak bila tidak datang dari server WP-MCP. Dua lapis:
 *  - 'authenticate' (prioritas 99): XML-RPC dan login biasa (termasuk application password lewat XML-RPC).
 *  - 'rest_authentication_errors' di bawah: REST dengan application password (jalur REST tidak melewati
 *    filter 'authenticate', sehingga lapis ini yang menjaganya).
 */
add_filter(
	'authenticate',
	static function ( $user ) {
		if ( ! wpmcp_user_is_ai( $user ) ) {
			return $user;
		}
		if ( defined( 'XMLRPC_REQUEST' ) && XMLRPC_REQUEST ) {
			return new WP_Error( 'wpmcp_xmlrpc_denied', 'Akun Editor AI tidak dapat memakai XML-RPC.' );
		}
		if ( ! wpmcp_request_from_server() ) {
			return new WP_Error( 'wpmcp_remote_denied', 'Akun Editor AI hanya dapat dipakai dari server WP-MCP.' );
		}
		return $user;
	},
	99
);

// Lapis kedua untuk REST: jangan berhenti hanya karena $result === true (application password sukses).
add_filter(
	'rest_authentication_errors',
	static function ( $result ) {
		if ( is_wp_error( $result ) ) {
			return $result;
		}
		if ( wpmcp_current_user_is_ai() && ! wpmcp_request_from_server() ) {
			return new WP_Error( 'wpmcp_remote_denied', 'Akun Editor AI hanya dapat dipakai dari server WP-MCP.', array( 'status' => 403 ) );
		}
		return $result;
	},
	99
);

add_action(
	'wp_login',
	static function ( $user_login, $user ) {
		if ( wpmcp_user_is_ai( $user ) ) {
			wp_logout();
			wp_die( esc_html__( 'Akun Editor AI tidak dipakai untuk login wp-admin. Gunakan WP-MCP.', 'wp-mcp-bridge' ), 403 );
		}
	},
	10,
	2
);

/* --------------------------------------------------------------------------
 * Persetujuan WP-MCP: aksi dari Claude Code disahkan manusia di wp-admin.
 * WP-MCP mengirim ringkasan aksi (POST /wpmcp/v1/pending, hanya akun AI); manusia menekan
 * Setujui/Tolak di wp-admin (cookie login + nonce; akun AI tidak bisa); WP-MCP membaca keputusan
 * (GET /wpmcp/v1/approvals/<id>) dan memetakan login ke aktornya sendiri.
 * ------------------------------------------------------------------------ */
function wpmcp_pending_get(): array {
	$all = get_option( WPMCP_PENDING_OPTION, array() );
	$now = time();
	foreach ( $all as $id => $a ) {
		if ( ( $a['expires_at'] ?? 0 ) < $now - DAY_IN_SECONDS ) {
			unset( $all[ $id ] );
		}
	}
	return $all;
}

function wpmcp_pending_save( array $all ): void {
	if ( count( $all ) > 200 ) {
		$all = array_slice( $all, -200, null, true );
	}
	update_option( WPMCP_PENDING_OPTION, $all, false );
}

function wpmcp_can_approve(): bool {
	return is_user_logged_in() && ! wpmcp_current_user_is_ai() && current_user_can( 'edit_others_posts' );
}

add_action(
	'rest_api_init',
	static function () {
		register_rest_route( 'wpmcp/v1', '/ping', array(
			'methods'             => 'GET',
			'permission_callback' => static function () {
				return current_user_can( 'edit_posts' );
			},
			'callback'            => static function () {
				return array(
					'plugin'                => 'wp-mcp-bridge',
					'version'               => WPMCP_BRIDGE_VERSION,
					'wp_version'            => get_bloginfo( 'version' ),
					'role_ok'               => wpmcp_current_user_is_ai(),
					'from_server'           => wpmcp_request_from_server(),
					'bridge_key'            => defined( 'WPMCP_BRIDGE_KEY' ) && WPMCP_BRIDGE_KEY ? 'aktif' : 'tidak diatur',
					'block_theme'           => function_exists( 'wp_is_block_theme' ) ? wp_is_block_theme() : false,
					'application_passwords' => wp_is_application_passwords_available(),
					'timezone'              => wp_timezone_string(),
				);
			},
		) );

		register_rest_route( 'wpmcp/v1', '/pending', array(
			'methods'             => 'POST',
			'permission_callback' => static function () {
				return wpmcp_current_user_is_ai();
			},
			'callback'            => static function ( WP_REST_Request $req ) {
				$id = sanitize_key( (string) $req->get_param( 'id' ) );
				if ( ! preg_match( '/^act_[a-f0-9]{8,16}$/', $id ) ) {
					return new WP_Error( 'wpmcp_bad_id', 'id aksi tidak sah', array( 'status' => 400 ) );
				}
				$all        = wpmcp_pending_get();
				$all[ $id ] = array(
					'id'           => $id,
					'tool'         => sanitize_key( (string) $req->get_param( 'tool' ) ),
					'level'        => sanitize_text_field( (string) $req->get_param( 'level' ) ),
					'summary'      => sanitize_textarea_field( (string) $req->get_param( 'summary' ) ),
					'impact'       => array_map( 'sanitize_text_field', (array) $req->get_param( 'impact' ) ),
					'readback'     => wp_json_encode( $req->get_param( 'readback' ) ),
					'requested_by' => sanitize_text_field( (string) $req->get_param( 'requested_by' ) ),
					'expires_at'   => (int) $req->get_param( 'expires_at' ),
					'decision'     => 'pending',
				);
				wpmcp_pending_save( $all );
				return array( 'stored' => $id );
			},
		) );

		register_rest_route( 'wpmcp/v1', '/approvals/(?P<id>act_[a-f0-9]{8,16})', array(
			'methods'             => 'GET',
			'permission_callback' => static function () {
				return wpmcp_current_user_is_ai();
			},
			'callback'            => static function ( WP_REST_Request $req ) {
				$all = wpmcp_pending_get();
				$a   = $all[ $req['id'] ] ?? null;
				if ( ! $a ) {
					return new WP_Error( 'wpmcp_not_found', 'aksi tidak ada', array( 'status' => 404 ) );
				}
				return array(
					'id'         => $a['id'],
					'decision'   => $a['decision'],
					'user_login' => $a['decided_by'] ?? null,
					'at'         => $a['decided_at'] ?? null,
				);
			},
		) );

		register_rest_route( 'wpmcp/v1', '/search-stats', array(
			'methods'             => 'GET',
			'permission_callback' => static function () {
				return current_user_can( 'edit_posts' );
			},
			'callback'            => static function () {
				$stats = get_option( 'wpmcp_empty_searches', array() );
				arsort( $stats );
				return array_slice( $stats, 0, 100, true );
			},
		) );
	}
);

add_action(
	'admin_menu',
	static function () {
		$all     = wpmcp_pending_get();
		$waiting = count( array_filter( $all, static fn( $a ) => 'pending' === $a['decision'] && $a['expires_at'] > time() ) );
		$label   = 'Persetujuan WP-MCP' . ( $waiting ? ' <span class="awaiting-mod">' . (int) $waiting . '</span>' : '' );
		add_menu_page( 'Persetujuan WP-MCP', $label, 'edit_others_posts', 'wpmcp-approvals', 'wpmcp_render_approvals', 'dashicons-yes-alt', 3 );
	}
);

function wpmcp_render_approvals(): void {
	if ( ! wpmcp_can_approve() ) {
		wp_die( esc_html__( 'Tidak berwenang.', 'wp-mcp-bridge' ), 403 );
	}
	$all = array_reverse( wpmcp_pending_get(), true );
	echo '<div class="wrap"><h1>Persetujuan WP-MCP</h1>';
	echo '<p>Aksi yang diminta lewat Claude Code menunggu keputusan manusia. Periksa ringkasannya; WP-MCP tetap memeriksa ulang kewenangan peran Anda (dan isi yang berubah) sebelum menjalankan.</p>';
	echo '<table class="widefat striped"><thead><tr><th>Aksi</th><th>Ringkasan</th><th>Dampak</th><th>Diminta</th><th>Status</th><th></th></tr></thead><tbody>';
	if ( ! $all ) {
		echo '<tr><td colspan="6">Tidak ada aksi.</td></tr>';
	}
	foreach ( $all as $a ) {
		$expired = $a['expires_at'] < time();
		echo '<tr><td><code>' . esc_html( $a['id'] ) . '</code><br>' . esc_html( $a['tool'] ) . ' (level ' . esc_html( $a['level'] ) . ')</td>';
		$readback = json_decode( (string) ( $a['readback'] ?? '' ), true );
		echo '<td>' . esc_html( $a['summary'] );
		if ( $readback ) {
			echo '<details><summary>Rincian lengkap</summary><pre style="white-space:pre-wrap;max-width:60em">'
				. esc_html( wp_json_encode( $readback, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES ) )
				. '</pre></details>';
		}
		echo '</td><td>' . esc_html( implode( '; ', (array) $a['impact'] ) ) . '</td>';
		echo '<td>' . esc_html( $a['requested_by'] ) . '</td>';
		$status = $expired && 'pending' === $a['decision'] ? 'kedaluwarsa' : $a['decision'];
		echo '<td>' . esc_html( $status ) . ( ! empty( $a['decided_by'] ) ? '<br>oleh ' . esc_html( $a['decided_by'] ) : '' ) . '</td><td>';
		if ( 'pending' === $a['decision'] && ! $expired ) {
			foreach ( array( 'approved' => 'Setujui', 'rejected' => 'Tolak' ) as $decision => $text ) {
				echo '<form method="post" action="' . esc_url( admin_url( 'admin-post.php' ) ) . '" style="display:inline">';
				wp_nonce_field( 'wpmcp_decide_' . $a['id'] );
				echo '<input type="hidden" name="action" value="wpmcp_decide"><input type="hidden" name="id" value="' . esc_attr( $a['id'] ) . '">';
				echo '<input type="hidden" name="decision" value="' . esc_attr( $decision ) . '">';
				submit_button( $text, 'approved' === $decision ? 'primary small' : 'secondary small', 'submit', false );
				echo '</form> ';
			}
		}
		echo '</td></tr>';
	}
	echo '</tbody></table></div>';
}

add_action(
	'admin_post_wpmcp_decide',
	static function () {
		$id = isset( $_POST['id'] ) ? sanitize_key( wp_unslash( $_POST['id'] ) ) : '';
		check_admin_referer( 'wpmcp_decide_' . $id );
		if ( ! wpmcp_can_approve() ) {
			wp_die( esc_html__( 'Tidak berwenang.', 'wp-mcp-bridge' ), 403 );
		}
		$decision = isset( $_POST['decision'] ) && 'approved' === $_POST['decision'] ? 'approved' : 'rejected';
		$all      = wpmcp_pending_get();
		if ( isset( $all[ $id ] ) && 'pending' === $all[ $id ]['decision'] && $all[ $id ]['expires_at'] >= time() ) {
			$all[ $id ]['decision']   = $decision;
			$all[ $id ]['decided_by'] = wp_get_current_user()->user_login;
			$all[ $id ]['decided_at'] = time();
			wpmcp_pending_save( $all );
		}
		wp_safe_redirect( admin_url( 'admin.php?page=wpmcp-approvals' ) );
		exit;
	}
);

/* --------------------------------------------------------------------------
 * Statistik pencarian kosong (bahan "konten yang dicari warga tapi belum ada").
 * ------------------------------------------------------------------------ */
add_action(
	'template_redirect',
	static function () {
		if ( ! is_search() || have_posts() || is_user_logged_in() ) {
			return;
		}
		$term = mb_strtolower( trim( get_search_query() ) );
		if ( '' === $term || mb_strlen( $term ) > 80 ) {
			return;
		}
		$stats          = get_option( 'wpmcp_empty_searches', array() );
		$stats[ $term ] = ( $stats[ $term ] ?? 0 ) + 1;
		if ( count( $stats ) > 500 ) {
			asort( $stats );
			$stats = array_slice( $stats, -400, null, true );
		}
		update_option( 'wpmcp_empty_searches', $stats, false );
	}
);

/* --------------------------------------------------------------------------
 * Tampilan: kotak ralat dan pencabutan, kotak status di editor.
 * ------------------------------------------------------------------------ */
add_action(
	'wp_head',
	static function () {
		echo '<style id="wpmcp-bridge">.wpmcp-ralat,.wpmcp-dicabut{border-left:4px solid #b45309;background:#fffbeb;padding:.75em 1em;margin-top:1.5em}.wpmcp-dicabut{border-color:#b91c1c;background:#fef2f2}</style>' . "\n";
	}
);

add_action(
	'add_meta_boxes',
	static function () {
		foreach ( array( 'post', 'page' ) as $type ) {
			add_meta_box( 'wpmcp-status', 'Status WP-MCP', static function ( $post ) {
				$labels = array(
					'draft'       => 'Draft (disusun operator-ai)',
					'revisi'      => 'Revisi (perintah admin-web)',
					'siap_tayang' => 'Siap tayang (menunggu pimpinan, terkunci)',
					'published'   => 'Tayang',
				);
				$state  = get_post_meta( $post->ID, '_wpmcp_state', true );
				echo '<p><strong>' . esc_html( $labels[ $state ] ?? 'Di luar WP-MCP' ) . '</strong></p>';
				$note = get_post_meta( $post->ID, '_wpmcp_reviewer_note', true );
				if ( $note ) {
					echo '<p>Catatan ke pimpinan: ' . esc_html( $note ) . '</p>';
				}
				if ( 'siap_tayang' === $state ) {
					echo '<p style="color:#b45309">Perubahan di sini setelah diajukan membatalkan persetujuan yang sedang menunggu (hash konten berubah).</p>';
				}
			}, $type, 'side', 'high' );
		}
	}
);
