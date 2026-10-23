// HUE RIG -- preview: the picture (dimmed) with each lamp drawn as a glowing
// disc in its current colour, at its place in the room.
//   input 0  the picture       input 1  lamp data (16 x 2: positions, colours)
//   uRes vec2, uDim float (how dark the picture underneath is)
uniform vec2  uRes;
uniform float uDim;
layout(location = 0) out vec4 fragColor;
void main()
{
    vec2  uv  = vUV.st;
    vec2  res = max(uRes, vec2(1.0));
    vec3  col = texture(sTD2DInputs[0], uv).rgb * uDim;
    float asp = res.x / res.y;
    for (int i = 0; i < 16; i++)
    {
        vec4 pos = texelFetch(sTD2DInputs[1], ivec2(i, 0), 0);
        if (pos.z < 0.5) continue;
        vec3 c   = texelFetch(sTD2DInputs[1], ivec2(i, 1), 0).rgb;
        vec2 d   = (uv - pos.xy) * vec2(asp, 1.0);
        float r  = length(d);
        float disc = 1.0 - smoothstep(0.045, 0.05, r);
        float ring = (1.0 - smoothstep(0.004, 0.007, abs(r - 0.053)));
        float glow = exp(-r * 9.0) * 0.8;
        col = mix(col, c, disc);
        col += c * glow;
        col = mix(col, vec3(0.85), ring * 0.6);
    }
    fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
