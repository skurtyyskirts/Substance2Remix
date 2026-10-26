"""The texture maps Substance2Remix moves between Painter and RTX Remix.

One row per AperturePBR texture input the RTX Remix Toolkit can ingest
(``TextureTypes`` in omni.flux.asset_importer.core, Toolkit 1.6.1). Remix
ingest types, shader inputs, Painter channels and export names are all
derived from this table.

Opacity has no row: AperturePBR has no opacity texture and reads opacity from
the albedo alpha, so the plugin carries Painter's Opacity channel there.
"""
from collections import namedtuple

PbrMap = namedtuple("PbrMap", (
    "key",             # plugin name for the map
    "label",           # shown in Settings
    "remix_input",     # AperturePBR shader input, without "inputs:"
    "ingest_type",     # Remix ingest texture type (normals: remix_api.ingest_type_for)
    "suffix",          # what Remix appends on ingest: <stem>.<suffix>.rtex.dds
    "file_suffix",     # exported file name: <material hash>_<file_suffix>
    "channels",        # Painter ChannelType names to try, current name first
    "channel_format",  # ChannelFormat used when the plugin adds the channel
    "color",           # RGB (True) or grayscale (False)
    "doc_map",         # Painter export documentMap name; None = read from the channel
    "painter_label",   # the Painter channel, as shown in the UI
    "user_label",      # label of the User channel that holds the map, if any
    "dds",             # (block format, gamma encoded) for maps Remix's default ingest drops
))

PBR_MAPS = (
    PbrMap(key="albedo", label="Albedo", remix_input="diffuse_texture", ingest_type="DIFFUSE",
           suffix="a", file_suffix="Albedo", channels=("BaseColor",), channel_format="sRGB8",
           color=True, doc_map="baseColor", painter_label="Base Color", user_label="", dds=None),
    # "_Normal" lets Remix's octahedral conversion produce "<hash>_OTH_Normal".
    PbrMap(key="normal", label="Normal", remix_input="normalmap_texture", ingest_type="NORMAL_OGL",
           suffix="n", file_suffix="Normal", channels=("Normal",), channel_format="RGB16F",
           color=True, doc_map=None, painter_label="Normal (with Height detail)", user_label="", dds=None),
    PbrMap(key="roughness", label="Roughness", remix_input="reflectionroughness_texture", ingest_type="ROUGHNESS",
           suffix="r", file_suffix="Roughness", channels=("Roughness",), channel_format="L8",
           color=False, doc_map="roughness", painter_label="Roughness", user_label="", dds=None),
    PbrMap(key="metallic", label="Metallic", remix_input="metallic_texture", ingest_type="METALLIC",
           suffix="m", file_suffix="Metallic", channels=("Metallic",), channel_format="L8",
           color=False, doc_map="metallic", painter_label="Metallic", user_label="", dds=None),
    PbrMap(key="height", label="Height (displacement)", remix_input="height_texture", ingest_type="HEIGHT",
           suffix="h", file_suffix="Height", channels=("Height",), channel_format="L16F",
           color=False, doc_map="height", painter_label="Height", user_label="", dds=None),
    PbrMap(key="emissive", label="Emissive", remix_input="emissive_mask_texture", ingest_type="EMISSIVE",
           suffix="e", file_suffix="Emissive", channels=("Emissive",), channel_format="sRGB8",
           color=True, doc_map="emissive", painter_label="Emissive", user_label="", dds=None),
    # The maps below go through the plugin's own DDS step (remix_api._extended_check_plugins).
    # Encodings follow TEXTURE_INFO in lightspeed.trex.asset_pipeline.core.
    PbrMap(key="anisotropy", label="Anisotropy", remix_input="anisotropy_texture", ingest_type="ANISOTROPY",
           suffix="an", file_suffix="Anisotropy", channels=("SpecularRoughnessAnisotropy", "Anisotropylevel"),
           channel_format="L8", color=False, doc_map=None, painter_label="Anisotropy Level", user_label="",
           dds=("bc4", False)),
    PbrMap(key="transmittance", label="Subsurface Transmittance", remix_input="subsurface_transmittance_texture",
           ingest_type="TRANSMITTANCE", suffix="tr", file_suffix="Transmittance",
           channels=("TransmissionColor", "AbsorptionColor"), channel_format="sRGB8", color=True, doc_map=None,
           painter_label="Transmission Color", user_label="", dds=("bc7", True)),
    # Painter has no thickness channel type, so this map lives in a labelled User channel.
    PbrMap(key="thickness", label="Subsurface Thickness", remix_input="subsurface_thickness_texture",
           ingest_type="MEASUREMENT_DISTANCE", suffix="md", file_suffix="Thickness", channels=(),
           channel_format="L8", color=False, doc_map=None, painter_label='User channel "Remix Thickness"',
           user_label="Remix Thickness", dds=("bc4", False)),
    # The Remix runtime reads single scattering as linear data, hence a linear channel.
    PbrMap(key="single_scattering", label="Subsurface Single Scattering",
           remix_input="subsurface_single_scattering_texture", ingest_type="SINGLE_SCATTERING", suffix="ss",
           file_suffix="SingleScattering", channels=("SubsurfaceColor", "ScatteringColor"), channel_format="RGB8",
           color=True, doc_map=None, painter_label="Subsurface Color", user_label="", dds=("bc7", False)),
)

MAPS_BY_KEY = {m.key: m for m in PBR_MAPS}
MAP_KEYS = tuple(m.key for m in PBR_MAPS)
EXTENDED_MAP_KEYS = tuple(m.key for m in PBR_MAPS if m.dds)

OPACITY = "opacity"
# Everything the user can switch on or off in Settings > Texture Maps.
TOGGLE_KEYS = MAP_KEYS + (OPACITY,)


def is_extended(key):
    """True for maps that Remix's default "Material" ingest pipeline drops."""
    m = MAPS_BY_KEY.get(key)
    return bool(m and m.dds)
