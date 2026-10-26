//- Substance2Remix: RTX Remix preview shader for Substance 3D Painter.
//- ==================================================================
//-
//- Shows every texture map Substance2Remix pushes to RTX Remix's AperturePBR
//- material. It is Painter's "PBR - Metal Rough with alpha blending" shader
//- plus three things that shader ignores:
//-   * Anisotropy: the Anisotropy Level channel stretches highlights along
//-     the mesh tangent, as Remix does (Remix has no anisotropy angle).
//-   * Subsurface: an approximation of Remix's subsurface look built from the
//-     Transmission Color (Remix transmittance), Subsurface Color (Remix single
//-     scattering) and "Remix Thickness" (User channel) maps.
//- Without those channels it renders exactly like the stock shader. RTX Remix
//- remains the reference for the final look.

//- ================================================
//- Import from libraries.
import lib-pbr.glsl
import lib-pbr-aniso.glsl
import lib-bent-normal.glsl
import lib-emissive.glsl
import lib-pom.glsl
import lib-utils.glsl

// Link Metal/Roughness MDL for Iray
//: metadata {
//:   "model":"painter_legacy",
//:   "mdl":"mdl::alg::materials::physically_metallic_roughness::physically_metallic_roughness"
//: }

//- Show back faces as there may be holes in front faces.
//: state cull_face off

//- Enable alpha blending (opacity rides in Remix's albedo alpha).
//: state blend over

//- Channels needed for metal/rough workflow are bound here.
//: param auto channel_basecolor
uniform SamplerSparse basecolor_tex;
//: param auto channel_roughness
uniform SamplerSparse roughness_tex;
//: param auto channel_metallic
uniform SamplerSparse metallic_tex;
//: param auto channel_specularlevel
uniform SamplerSparse specularlevel_tex;
//: param auto channel_opacity
uniform SamplerSparse opacity_tex;

//- Remix anisotropy (Painter: Anisotropy Level / Specular anisotropy).
//: param auto channel_anisotropylevel
uniform SamplerSparse anisotropylevel_tex;

//- Remix subsurface transmittance (Painter: Transmission Color / Absorption color).
//: param auto channel_absorptioncolor
uniform SamplerSparse remix_transmittance_tex;
//- Remix subsurface single scattering albedo (Painter: Subsurface Color / Scattering color).
//: param auto channel_scatteringcolor
uniform SamplerSparse remix_single_scattering_tex;

//- Remix subsurface thickness lives in a User channel labelled "Remix Thickness".
//: param auto channel_user0
uniform SamplerSparse remix_user0_tex;
//: param auto channel_user1
uniform SamplerSparse remix_user1_tex;
//: param auto channel_user2
uniform SamplerSparse remix_user2_tex;
//: param auto channel_user3
uniform SamplerSparse remix_user3_tex;

//: param custom {
//:   "default": 0,
//:   "label": "Remix Thickness channel",
//:   "widget": "combobox",
//:   "values": {
//:     "None": -1,
//:     "User0": 0,
//:     "User1": 1,
//:     "User2": 2,
//:     "User3": 3
//:   },
//:   "group": "RTX Remix Preview",
//:   "description": "<html><head/><body><p>The User channel holding the Remix subsurface thickness map. Substance2Remix sets this when it adds the channel.</p></body></html>"
//: }
uniform int remixThicknessChannel;

//: param custom {
//:   "default": 1.0,
//:   "label": "Subsurface preview strength",
//:   "min": 0.0,
//:   "max": 4.0,
//:   "group": "RTX Remix Preview",
//:   "description": "<html><head/><body><p>How strongly light seen through the surface shows where Remix subsurface maps are painted. A viewport approximation only.</p></body></html>"
//: }
uniform float remixSubsurfaceStrength;

//: param custom {
//:   "default": 0.5,
//:   "label": "Default thickness",
//:   "min": 0.0,
//:   "max": 1.0,
//:   "group": "RTX Remix Preview",
//:   "description": "<html><head/><body><p>Thickness assumed where no Remix Thickness map is painted.</p></body></html>"
//: }
uniform float remixDefaultThickness;

//- Thickness value (r) and coverage (g) from the selected User channel.
vec2 sampleRemixThickness(SparseCoord coord)
{
  vec4 v = vec4(0.0);
  if (remixThicknessChannel == 0) v = textureSparse(remix_user0_tex, coord);
  else if (remixThicknessChannel == 1) v = textureSparse(remix_user1_tex, coord);
  else if (remixThicknessChannel == 2) v = textureSparse(remix_user2_tex, coord);
  else if (remixThicknessChannel == 3) v = textureSparse(remix_user3_tex, coord);
  return v.rg;
}

//- Shader entry point.
void shade(V2F inputs)
{
  // Apply parallax occlusion mapping if possible
  vec3 viewTS = worldSpaceToTangentSpace(getEyeVec(inputs.position), inputs);
  applyParallaxOffset(inputs, viewTS);

  // Fetch material parameters, and conversion to the specular/roughness model
  float roughness = getRoughness(roughness_tex, inputs.sparse_coord);
  vec3 baseColor = getBaseColor(basecolor_tex, inputs.sparse_coord);
  float metallic = getMetallic(metallic_tex, inputs.sparse_coord);
  float specularLevel = getSpecularLevel(specularlevel_tex, inputs.sparse_coord);
  float anisotropyLevel = getAnisotropyLevel(anisotropylevel_tex, inputs.sparse_coord);

  vec3 diffColor = generateDiffuseColor(baseColor, metallic);
  vec3 specColor = generateSpecularColor(specularLevel, baseColor, metallic);

  // Get detail (ambient occlusion) and global (shadow) occlusion factors
  // separately in order to blend the bent normals properly
  float shadowFactor = getShadowFactor();
  float occlusion = getAO(inputs.sparse_coord, true, use_bent_normal);
  float specOcclusion = specularOcclusionCorrection(
    use_bent_normal ? shadowFactor : occlusion * shadowFactor,
    metallic,
    roughness);

  // Tangent-aligned frame (anisotropy angle 0), the same frame the stock shader uses.
  LocalVectors vectors = computeLocalFrame(inputs);
  computeBentNormal(vectors,inputs);

  // Remix subsurface approximation: light from behind the surface, filtered by
  // the transmittance color over the painted thickness and tinted by the single
  // scattering albedo. Only where at least one subsurface map is painted.
  vec4 transmittanceSample = textureSparse(remix_transmittance_tex, inputs.sparse_coord);
  vec4 scatteringSample = textureSparse(remix_single_scattering_tex, inputs.sparse_coord);
  vec2 thicknessSample = sampleRemixThickness(inputs.sparse_coord);
  float subsurfacePresence = max(max(transmittanceSample.a, scatteringSample.a), thicknessSample.g);
  vec3 subsurfaceShading = vec3(0.0);
  if (subsurfacePresence > 0.0) {
    vec3 transmittance = mattePremultiplied(transmittanceSample, vec3(0.5));
    vec3 scatteringAlbedo = mattePremultiplied(scatteringSample, vec3(0.5));
    float thickness = thicknessSample.r + remixDefaultThickness * (1.0 - thicknessSample.g);
    // Beer-Lambert: the transmittance color is reached at half the thickness range.
    vec3 throughput = pow(max(transmittance, vec3(1e-3)), vec3(2.0 * thickness));
    subsurfaceShading = remixSubsurfaceStrength * subsurfacePresence * (1.0 - metallic)
      * throughput * scatteringAlbedo * envIrradiance(-vectors.normal);
  }

  // Feed parameters for a physically based BRDF integration
  alphaOutput(getOpacity(opacity_tex, inputs.sparse_coord));
  emissiveColorOutput(pbrComputeEmissive(emissive_tex, inputs.sparse_coord));
  diffuseShadingOutput(occlusion * shadowFactor * pbrComputeDiffuse(getDiffuseBentNormal(vectors), diffColor)
    + occlusion * subsurfaceShading);
  if (anisotropyLevel > 0.0) {
    vec2 roughnessAniso = generateAnisotropicRoughness(roughness, anisotropyLevel);
    specularShadingOutput(specOcclusion * pbrComputeSpecularAnisotropic(vectors, specColor, roughnessAniso, occlusion, getBentNormalSpecularAmount()));
  } else {
    specularShadingOutput(specOcclusion * pbrComputeSpecular(vectors, specColor, roughness, occlusion, getBentNormalSpecularAmount()));
  }
}
